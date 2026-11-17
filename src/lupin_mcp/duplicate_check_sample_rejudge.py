"""
A sample re-judge of the interim judge, with a corrected flag rate.

While one model judged the backlog, its rulings may be off.
When the reference model returns, this tool draws a seeded random sample of the definitions the interim model ruled itself.
It judges them again with the reference model on a slot of its own.
Then it corrects the interim model's flag rate with what the reference model said.

The estimate is the interim model's flag rate over every pair verdict it made.
To that it adds the average gap between the two models on the sampled pairs.
The first part comes from the `pairs` counts the daily check records in each result file.
The gap is a ratio over whole definitions, because the pairs of one definition are not independent.
The interval is 95 percent and normal, from the variance of the rate and the variance of the gap added.

Without --go the tool prints the sample and the plan and makes no model call.
With --go it makes up to one call for each sampled definition, plus one more for each reply it has to ask for again.

Exit 0 means the plan or the estimate was printed. Exit 3 means it could not be made, with the reason printed.
"""
import argparse
import datetime
import math
import pathlib
import sys

import cosa.utils.util as cu
from cosa.repo import code_health_settings as chs
from cosa.repo.duplicate_check.judge import FLAG_VERDICTS
from cosa.repo.duplicate_check.proof import proof_cli
from lupin_mcp import duplicate_check_daily as daily
from lupin_mcp import duplicate_check_drift as drift
from lupin_mcp import duplicate_check_self_consistency as sc
from lupin_mcp import duplicate_check_status as dcs
from lupin_mcp.reuse_e2e import Z_95
from lupin_mcp.reuse_needset.report_rollup import table

MIN_SLOT      = 2             # slots 0 and 1 hold the interim model's rulings; a saved ruling of any model is reused on its slot, so the reference model needs a slot of its own
EXIT_NOT_MADE = 3


def population_pairs( folder, model, unreadable ):
    """
    Sum the pair verdicts a model made itself over every run.

    Requires:
        - unreadable is a list the unreadable result files are added to

    Ensures:
        - returns ( rows, flagged, runs ): the sums of the `pairs` entry for model in each result file, and the names of the files that held one
        - a file with no entry for the model, such as one written before the field existed, adds nothing
    """
    rows = flagged = 0
    runs = []
    for name, _doc, pair in drift.run_pairs( folder, model, unreadable ):
        rows    += pair[ "rows" ]
        flagged += pair[ "flagged" ]
        runs.append( name )
    return rows, flagged, runs


def frame_ids( folder, model, runs ):
    """
    List the definitions a sample may be drawn from.

    Ensures:
        - returns the sorted ids of the definitions the model judged itself (sc.own_lines) whose run file is in runs, so each sampled definition belongs to a run whose pair counts are in the population
    """
    return sorted( i for i, line in sc.own_lines( folder, model ).items() if line[ "run_file" ] in set( runs ) )


def matched_pairs( first, second ):
    """
    Pair up what the two models said about the same ( definition, candidate ).

    Requires:
        - first and second are judge_run verdict rows with id, candidate and verdict

    Ensures:
        - returns ( by_definition, unmatched ): by_definition is { definition id: [ ( interim flag, reference flag ), ... ] } in sorted pair order, each flag 0 or 1, over the pairs both passes ruled
        - unmatched counts the pairs only one pass ruled
    """
    flags = lambda rows: { ( r[ "id" ], r[ "candidate" ] ): 1 if r[ "verdict" ] in FLAG_VERDICTS else 0 for r in rows }
    a, b  = flags( first ), flags( second )
    by    = {}
    for key in sorted( set( a ) & set( b ) ): by.setdefault( key[ 0 ], [] ).append( ( a[ key ], b[ key ] ) )
    return by, len( set( a ) ^ set( b ) )


def estimate( total_rows, total_flagged, by_definition, z=Z_95 ):
    """
    Estimate the reference model's flag rate over the interim model's whole pair population.

    Requires:
        - total_rows is above 0 and total_flagged is from 0 to total_rows; by_definition is matched_pairs' first answer

    Ensures:
        - returns { rate, gap, low, high, definitions, pairs, interim_rate, reference_rate, sample_interim_rate }
        - interim_rate is total_flagged / total_rows
        - gap is the sum of ( reference - interim ) over the matched pairs, divided by their count
        - rate is interim_rate + gap, and low and high are rate -/+ z standard errors, kept inside 0 to 1
        - the variance is interim_rate * ( 1 - interim_rate ) / total_rows plus the cluster-ratio variance of the gap, which treats each definition as one unit
        - with fewer than 2 definitions that have a matched pair, gap-variance cannot be estimated, so low and high are None
        - with no matched pair at all, rate and gap are None as well

    Raises:
        - ValueError when total_rows is not above 0
    """
    if total_rows <= 0: raise ValueError( "the interim model made no pair verdict in the runs with pair counts" )
    interim = total_flagged / total_rows
    units   = [ ( len( p ), sum( y - f for f, y in p ) ) for p in by_definition.values() ]
    n       = sum( u[ 0 ] for u in units )
    out     = { "definitions": len( units ), "pairs": n, "interim_rate": interim, "rate": None, "gap": None, "low": None, "high": None, "reference_rate": None, "sample_interim_rate": None }
    if n == 0: return out
    gap     = sum( u[ 1 ] for u in units ) / n
    out.update( gap=gap, rate=interim + gap,
                sample_interim_rate=sum( f for p in by_definition.values() for f, _ in p ) / n, reference_rate=sum( y for p in by_definition.values() for _, y in p ) / n )
    m = len( units )
    if m < 2: return out
    gap_variance = sum( ( d - gap * k ) ** 2 for k, d in units ) / ( ( m - 1 ) * m * ( n / m ) ** 2 )
    se           = math.sqrt( interim * ( 1 - interim ) / total_rows + gap_variance )
    out.update( low=max( 0.0, out[ "rate" ] - z * se ), high=min( 1.0, out[ "rate" ] + z * se ) )
    return out


def render( interim_model, reference_model, size, seed, slot, population, groups, est=None, missing=(), calls=0, unmatched=0 ):
    """
    Print the plan, or the estimate when the sample was re-judged.

    Requires:
        - population is population_pairs' answer; groups is sc.runs_of's answer; est is estimate's answer for a live run

    Ensures:
        - returns the text: a title, the sample by run file and the population counts
        - a plan says that no call was made and how many the sample may need
        - a live run adds the estimate, the interval, the gap, the matched and unmatched pair counts, the calls made and the ids left out
        - a missing figure reads n/a
    """
    ids   = [ i for run in groups.values() for i in run ]
    pct   = lambda v: "n/a" if v is None else f"{100 * v:.1f}%"
    lines = [ f"# Sample re-judge of {interim_model} with {reference_model}", "",
              f"Sample of {len( ids )} definitions (asked for {size}, seed {seed}, slot {slot}), from {len( groups )} run file(s) with pair counts.", "",
              table( [ "run file", "sampled" ], [ [ run, len( groups[ run ] ) ] for run in groups ] ), "",
              f"Population: {population[ 0 ]} pair verdicts by {interim_model}, {population[ 1 ]} flagged ({pct( population[ 1 ] / population[ 0 ] if population[ 0 ] else None )}).", "" ]
    if est is None: return "\n".join( lines + [ f"Plan only: no model call was made. The re-judge may make up to {len( ids )} calls, and one more for each reply it must ask for again; add --go to run it." ] )
    lines += [ table( [ "definitions", "matched pairs", "interim rate on the sample", "reference rate on the sample", "gap", "estimated flag rate", "95% interval" ],
                      [ [ est[ "definitions" ], est[ "pairs" ], pct( est[ "sample_interim_rate" ] ), pct( est[ "reference_rate" ] ), pct( est[ "gap" ] ), pct( est[ "rate" ] ),
                          "n/a" if est[ "low" ] is None else f"{pct( est[ 'low' ] )} to {pct( est[ 'high' ] )}" ] ] ), "", f"Pairs only one pass ruled, left out of the gap: {unmatched}.", f"Model calls made: {calls}." ]
    if missing: lines += [ "", f"Left out, because a pass could not be replayed or judged: {', '.join( sorted( missing ) )}" ]
    return "\n".join( lines )


def main( argv=None, out=None, parts=None, now=None, run=None ):
    """
    Print the sample re-judge plan, or run it with --go.

    Requires:
        - --ruled-by names the interim model, --rejudge-with the reference model and --size the sample size; none has a default, because a model id belongs to the INI file or the caller
        - --go needs --claude-cli-path, and makes model calls

    Ensures:
        - without --go, prints the plan and returns 0 with no model call and nothing written
        - with --go, prints the estimate and returns 0
        - prints a refusal line with the reason and returns 3 when the slot is below MIN_SLOT, the size is below 1, the folder or a file cannot be read, nothing can be sampled, the lock is held or the day's budget is spent
    """
    ap = argparse.ArgumentParser( description="Judge a sample of the interim judge's rulings again with the reference model." )
    ap.add_argument( "--ruled-by", required=True, help="the interim model whose rulings are sampled" )
    ap.add_argument( "--rejudge-with", required=True, help="the reference model that judges the sample again" )
    ap.add_argument( "--size", type=int, required=True )
    ap.add_argument( "--slot", type=int, default=MIN_SLOT )
    ap.add_argument( "--seed", type=int, default=None, help="default is the date as YYYYMMDD" )
    ap.add_argument( "--check-dir", default=None )
    ap.add_argument( "--go", action="store_true", help="make the model calls; without it the command only prints the plan" )
    ap.add_argument( "--claude-cli-path", default=None )
    ap.add_argument( "--root", default=None )
    ap.add_argument( "--parallel", type=int, default=proof_cli.DEFAULT_PARALLEL )
    a    = ap.parse_args( argv )
    out  = out if out is not None else sys.stdout
    when = now or datetime.datetime.now().astimezone()
    try:
        if a.slot < MIN_SLOT: raise ValueError( f"--slot {a.slot} is below {MIN_SLOT}: slots below it hold the interim model's rulings, and a saved ruling is reused before any call" )
        if a.size < 1: raise ValueError( "--size must be at least 1" )
        if a.go and not a.claude_cli_path: raise ValueError( "--go needs --claude-cli-path" )
        root   = a.root or cu.get_project_root()
        folder = pathlib.Path( a.check_dir ) if a.check_dir else dcs.folder_of( root )
        seed   = a.seed if a.seed is not None else int( when.strftime( "%Y%m%d" ) )
        pop    = population_pairs( folder, a.ruled_by, [] )
        ids    = sc.draw( frame_ids( folder, a.ruled_by, pop[ 2 ] ), a.size, seed )
        if not ids: raise ValueError( f"no definition that {a.ruled_by} judged itself belongs to a run with pair counts" )
        groups = sc.runs_of( folder, a.ruled_by, ids )
        if not a.go: text = render( a.ruled_by, a.rejudge_with, a.size, seed, a.slot, pop, groups )
        else:
            first, second, missing, calls = ( run or sc.live_run )( root, folder, a.ruled_by, groups, parts or daily.live_parts(), a.claude_cli_path, a.parallel, when, a.rejudge_with, a.slot )
            by, unmatched = matched_pairs( first, second )
            text = render( a.ruled_by, a.rejudge_with, a.size, seed, a.slot, pop, groups, estimate( pop[ 0 ], pop[ 1 ], by ), missing, calls, unmatched )
    except ( OSError, ValueError, RuntimeError, chs.CodeHealthSettingError, daily.SpendRefused ) as e:
        print( f"REFUSING: {type( e ).__name__}: {e}. Nothing was made.", file=out )
        return EXIT_NOT_MADE
    print( text, file=out )
    return 0


if __name__ == "__main__":  # pragma: no cover - thin process entry, main() is tested
    sys.exit( main() )
