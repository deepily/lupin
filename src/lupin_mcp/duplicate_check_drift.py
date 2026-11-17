"""
The weekly drift report of the interim duplicate-check judge.

It reads files the daily check already wrote and makes no model call.
Two tables come out of it.
The first is the weekly flag rate of one model.
It is set beside Fable's rate on the proof and Fable's rate on the backlog before the switch.
The second is the triage outcomes by the model that ruled each finding.

The flag rate is the share of pair verdicts, each a definition against one candidate, that the judge flagged.
The weekly counts come from the `pairs` field of each result file, which holds a model's own verdicts and never a reused ruling.
The backlog rate comes from the judge ledgers the Claude Code versions wrote before the cut-off day, whose keys name the model that ruled.
The triage table joins verdicts.jsonl to the findings of each result file, which carry judge_model.

Exit 0 means the report was made. Exit 3 means it could not be, with the reason printed.
"""
import argparse
import datetime
import json
import pathlib
import sys

import cosa.utils.util as cu
from cosa.repo import code_health_settings as chs
from cosa.utils import jsonl_file
from cosa.repo.duplicate_check import ledger_merge
from cosa.repo.duplicate_check.judge import FLAG_VERDICTS
from lupin_mcp import duplicate_check_status as dcs
from lupin_mcp import reuse_behaviour as rb
from lupin_mcp.reuse_e2e import wilson
from lupin_mcp.reuse_needset.report_rollup import share, table

MANIFEST        = "interim-judge-manifest.jsonl"
PROOF_FLAG_RATE = 0.15                  # Fable's flag rate on the proof, from the Opus interim judge plan
EXIT_NOT_MADE   = 3
SHIFT_HEADERS   = ( "week of", "pair verdicts", "flagged", "rate", "against the proof's rate", "against the backlog rate" )
TRIAGE_HEADERS  = ( "judge model", "findings", "duplicate", "extend", "distinct", "not ruled yet", "real of ruled", "of which reused" )
NO_RUN_FILE     = "result files that cannot be read"
NO_MODEL        = "no model recorded"   # the label of findings written before result files carried judge_model
KEY_MODEL_AT    = 4                     # the model id inside a judge ledger key: stage|old|new|prompt|model|slot


def week_of_text( stamp ):
    """
    Name the Monday of the week a time falls in.

    Requires:
        - stamp is an ISO-8601 text that starts with a date

    Ensures:
        - returns the ISO date of that week's Monday, read from the date as written, so a time zone never moves it

    Raises:
        - ValueError when the text does not start with an ISO date
    """
    day = datetime.date.fromisoformat( stamp[ :10 ] )
    return ( day - datetime.timedelta( days=day.weekday() ) ).isoformat()


def run_documents( folder, unreadable ):
    """
    Read the daily check's result files.

    Ensures:
        - returns ( file name, document ) for each file in folder whose name is a run's, in name order
        - a file that is not a JSON object adds its name to unreadable and is left out
    """
    docs = []
    for path, doc in rb.check_documents( folder ):
        if doc is None: unreadable.append( path.name )
        else: docs.append( ( path.name, doc ) )
    return docs


def run_pairs( folder, model, unreadable ):
    """
    List the pair counts a model made itself in each result file.

    Requires:
        - unreadable is a list the unreadable result files are added to

    Ensures:
        - returns ( file name, document, pair ) for each readable result file with a `pairs` entry for model, in name order, with pair that entry ( { rows, flagged } )
        - a file with no entry for the model, such as one written before the field existed, is left out
    """
    found = []
    for name, doc in run_documents( folder, unreadable ):
        pair = ( doc.get( "pairs" ) or {} ).get( model )
        if pair is not None: found.append( ( name, doc, pair ) )
    return found


def weekly_flags( folder, model, unreadable ):
    """
    Count the model's own pair verdicts and flags for each week.

    Ensures:
        - returns { Monday date: ( rows, flagged ) } in date order, summed from the `pairs` entry for model in each result file, grouped by the week of the file's started_at
        - a file with no pairs entry for the model, such as one written before the field existed, adds nothing
    """
    weeks = {}
    for _name, doc, pair in run_pairs( folder, model, unreadable ):
        week = weeks.setdefault( week_of_text( doc[ "started_at" ] ), [ 0, 0 ] )
        week[ 0 ] += pair[ "rows" ]
        week[ 1 ] += pair[ "flagged" ]
    return { week: tuple( weeks[ week ] ) for week in sorted( weeks ) }


def ledger_counts( path, model ):
    """
    Count the pair verdicts one judge ledger holds for a model.

    Ensures:
        - returns ( rows, flagged ) over the rulings of every ledger line whose key names model as the model that ruled
        - a line that holds no rulings, such as a binding line or an unreadable answer, adds nothing
    """
    rows = flagged = 0
    for line in jsonl_file.read_jsonl( path ):
        if "key" not in line or line[ "key" ].split( "|" )[ KEY_MODEL_AT ] != model: continue
        rulings = line[ "value" ].get( "rulings", [] )
        rows    += len( rulings )
        flagged += sum( 1 for r in rulings if r[ "verdict" ] in FLAG_VERDICTS )
    return rows, flagged


def backlog_ledgers( folder, before ):
    """
    List the version ledgers that closed before a day.

    Ensures:
        - returns ledger_merge.rotated_files( folder, closed_before=before ): the rotated version ledgers whose last change falls on a day earlier than before, oldest version first
        - the live judge-ledger.jsonl is never listed, because it holds rulings of every day
    """
    return ledger_merge.rotated_files( folder, closed_before=before )


def backlog_rate( folder, model, before ):
    """
    Measure a model's flag rate over the ledgers that closed before a day.

    Ensures:
        - returns ( rows, flagged, ledgers ) summed over backlog_ledgers( folder, before ), with ledgers the file names used
    """
    paths = backlog_ledgers( folder, before )
    parts = [ ledger_counts( p, model ) for p in paths ]
    return sum( r for r, _ in parts ), sum( f for _, f in parts ), [ p.name for p in paths ]


def shift_table( folder, model, baseline_model, before, unreadable ):
    """
    Build the weekly flag rate table.

    Ensures:
        - returns ( table text, backlog ) where backlog is backlog_rate's answer for the baseline model
        - one row for each week the model ruled any pair, with its counts, its rate and where the proof's rate and the backlog rate sit against the week's interval
        - no rows when the model ruled nothing
    """
    backlog = backlog_rate( folder, baseline_model, before )
    ref     = backlog[ 1 ] / backlog[ 0 ] if backlog[ 0 ] else None
    rows    = [ [ week, judged, flagged, share( flagged, judged ), against( PROOF_FLAG_RATE, flagged, judged ), against( ref, flagged, judged ) ] for week, ( judged, flagged ) in weekly_flags( folder, model, unreadable ).items() ]
    return table( SHIFT_HEADERS, rows ), backlog


def against( reference, flagged, judged ):
    """
    Say where a reference rate sits against one week's interval.

    Requires:
        - reference is a rate from 0 to 1, or None; 0 <= flagged <= judged

    Ensures:
        - returns "n/a" when there is no reference or nothing was judged
        - returns "within" when the reference lies inside the week's Wilson interval, "above reference" when the whole interval is above it, and "below reference" when the whole interval is below it
    """
    if reference is None or judged == 0: return "n/a"
    low, high = wilson( flagged, judged )
    if reference < low: return "above reference"
    if reference > high: return "below reference"
    return "within"


def finding_judges( folder, unreadable ):
    """
    Read each finding's judge model from the result files.

    Ensures:
        - returns { ( run file stem, finding id ): ( judge_model, reused ) } for every finding of every result file in folder; reused is True when the finding carries reused_from_model
        - a file that cannot be read adds its name to unreadable, and a run that failed before judging has no findings
        - a finding with no judge_model is kept, under NO_MODEL, because every finding written before the field existed has none
    """
    got = {}
    for name, doc in run_documents( folder, unreadable ):
        for f in doc.get( "findings" ) or []:
            got[ ( pathlib.Path( name ).stem, f[ "id" ] ) ] = ( f.get( "judge_model", NO_MODEL ), "reused_from_model" in f )
    return got


def triage_table( folder, unreadable ):
    """
    Build the triage outcomes table, one row for each judge model.

    Ensures:
        - counts each finding once under its judge_model, by the last verdict logged for it in verdicts.jsonl
        - a finding with no verdict counts as not ruled yet
        - real of ruled is share( duplicate + extend, ruled ), the same rule as the daily table
        - of which reused counts the model's findings that were ruled from a saved ruling
        - a verdict whose finding no result file lists is left out of every row
        - no rows when no result file holds a finding

    Raises:
        - ValueError, from the verdict reader, when verdicts.jsonl holds a line that is not a verdict record
    """
    judges   = finding_judges( folder, unreadable )
    verdicts = rb.read_verdicts( folder )
    tally    = {}
    for ( stem, finding ), ( model, reused ) in sorted( judges.items() ):
        row = tally.setdefault( model, { "findings": 0, "reused": 0, **{ v: 0 for v in rb.REAL_VERDICTS + rb.NOT_VERDICTS }, "open": 0 } )
        verdict = verdicts.get( ( stem, finding ) )
        row[ "findings" ] += 1
        row[ "reused" ]   += 1 if reused else 0
        row[ verdict if verdict is not None else "open" ] += 1
    rows = []
    for model in sorted( tally ):
        t     = tally[ model ]
        real  = t[ "DUPLICATE" ] + t[ "EXTEND" ]
        rows.append( [ model, t[ "findings" ], t[ "DUPLICATE" ], t[ "EXTEND" ], t[ "DISTINCT" ], t[ "open" ], share( real, real + t[ "DISTINCT" ] ), t[ "reused" ] ] )
    return table( TRIAGE_HEADERS, rows )


def report( folder, model, baseline_model, before ):
    """
    Make the drift report.

    Requires:
        - folder is the daily check's result folder; model and baseline_model are model ids; before is an ISO date

    Ensures:
        - returns the text: a title, the weekly flag table, the backlog line, the triage table and, when any file could not be read, a line naming them
        - makes no model call and writes nothing

    Raises:
        - ValueError when before is not an ISO date, or verdicts.jsonl holds a bad line
        - OSError when the folder cannot be listed
    """
    datetime.date.fromisoformat( before )
    unreadable = []
    flags, backlog = shift_table( folder, model, baseline_model, before, unreadable )
    triage = triage_table( folder, unreadable )
    lines = [ f"# Interim judge drift report: {model}", "", f"Weekly flag rate of {model}: its own pair verdicts only, never a reused ruling.", "", flags, "",
              f"Fable's rate on the proof: {share( round( PROOF_FLAG_RATE * 100 ), 100 )}.",
              f"{baseline_model} before {before}, from {len( backlog[ 2 ] )} version ledger(s) ({', '.join( backlog[ 2 ] ) or 'none'}): {share( backlog[ 1 ], backlog[ 0 ] )}.", "", "## Triage outcomes by judge model", "", triage ]
    if NO_MODEL in triage: lines += [ "", f"The row '{NO_MODEL}' holds the findings written before result files named their judge; the model that ruled them is not recorded." ]
    if unreadable: lines += [ "", f"{NO_RUN_FILE}: {', '.join( sorted( set( unreadable ) ) )}" ]
    return "\n".join( lines )


def main( argv=None, out=None, config=None ):
    """
    Print the drift report from the command line.

    Requires:
        - --baseline-model names the model whose backlog rate is the reference; it has no default, because the id belongs to the INI file or the caller
        - --model defaults to the `duplicate check judge model` INI key, read through config or the process's own manager

    Ensures:
        - prints the report and returns 0
        - prints a refusal line with the reason and returns 3 when the model key, the folder, a date or a file cannot be read
        - reads files only; no model call, no write
    """
    ap = argparse.ArgumentParser( description="The weekly drift report of the interim duplicate-check judge." )
    ap.add_argument( "--baseline-model", required=True, help="the model whose rate on the backlog before --before is the reference" )
    ap.add_argument( "--model", default=None, help="the model under watch; default is the INI judge model" )
    ap.add_argument( "--before", default="2026-11-11", help="the day the backlog rate stops, as YYYY-MM-DD" )
    ap.add_argument( "--check-dir", default=None, help="the daily duplicate check's result folder" )
    a   = ap.parse_args( argv )
    out = out if out is not None else sys.stdout
    try:
        model  = a.model or chs.model_id( chs.JUDGE_MODEL_KEY, config )
        folder = pathlib.Path( a.check_dir ) if a.check_dir else dcs.folder_of( cu.get_project_root() )
        text   = report( folder, model, a.baseline_model, a.before )
    except ( OSError, ValueError, chs.CodeHealthSettingError ) as e:
        print( f"REFUSING: {type( e ).__name__}: {e}. Nothing was made.", file=out )
        return EXIT_NOT_MADE
    print( text, file=out )
    return 0


if __name__ == "__main__":  # pragma: no cover - thin process entry, main() is tested
    sys.exit( main() )
