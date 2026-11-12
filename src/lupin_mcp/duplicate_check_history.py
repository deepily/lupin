"""
The run history of the daily duplicate check: one line per run, and a table reader.

Every run, successful or failed, appends one line with the same keys, so a time series needs no per-file shape handling.
The per-run result file carries the same schema_version, started_at and mode keys. A failed run fills the keys it
could not measure with None, never with a made-up zero, so a gap reads as a gap.
Eight result files written before the history existed are added by the backfill; each backfilled line says so.
"""
import argparse
import datetime
import json
import pathlib
import re
import sys

import cosa.utils.util as cu
from cosa.repo import code_health_settings as chs

SCHEMA_VERSION = 2
RUNS_FILE      = "runs.jsonl"
FOLDER         = "duplicate-check-daily"
MODE_DAILY     = "daily"
MODE_BASELINE  = "baseline"
MEASURED       = ( "ok", "carried" )                                 # statuses whose carried count is a measurement
RUN_FILE       = re.compile( r"^(\d{4})-(\d{2})-(\d{2})-(\d{2})(\d{2})(\d{2})-([a-z]+)\.json$" )
UNKNOWN_COMMIT = "unknown"
FILING_KEYS    = ( "filed", "already_filed", "queued_for_retry", "refused" )
TABLE_COLUMNS  = ( ( "started_at", "started" ), ( "mode", "mode" ), ( "trigger", "trigger" ), ( "status", "status" ), ( "judge_calls", "calls" ),
                   ( "judged", "judged" ), ( "carried", "carried" ), ( "findings", "findings" ), ( "groups", "groups" ), ( "filed", "filed" ),
                   ( "elapsed_seconds", "secs" ) )


def failure_of( doc ):
    """
    Say in one string why a run failed.

    Requires:
        - doc is a result document
    Ensures:
        - returns None for a run that did not fail
        - otherwise returns the stage or prerequisite, then the error, refusal or detail, whichever the document holds, joined by ": "
    """
    if doc[ "status" ] != "failed": return None
    what = doc.get( "stage" ) or doc.get( "prerequisite" ) or "unknown"
    why  = doc.get( "error" ) or doc.get( "refusal" ) or doc.get( "detail" )
    return f"{what}: {why}" if why else what


def started_from_name( name ):
    """
    Read a run's start time off its result file name.

    Requires:
        - name is <date>-<HHMMSS>-<trigger>.json
    Ensures:
        - returns the ISO-8601 time in the host's time zone
    Raises:
        - ValueError when the name has another shape
    """
    m = RUN_FILE.match( name )
    if m is None: raise ValueError( f"{name!r} is not a result file name" )
    year, month, day, hour, minute, second = ( int( g ) for g in m.groups()[ :6 ] )
    return datetime.datetime( year, month, day, hour, minute, second ).astimezone().isoformat()


def counts_of( filing ):
    """
    Count what the filer handled.

    Requires:
        - filing is the filer's answer, or None when the run had no filer
    Ensures:
        - returns { filed, already_filed, queued_for_retry, refused } as counts; a list counts by length and a number stands as it is
        - each is None when the run had no filer or the filer raised
    """
    ok = isinstance( filing, dict ) and "error" not in filing
    return { k: ( len( filing[ k ] ) if isinstance( filing[ k ], list ) else filing[ k ] ) if ok and k in filing else None for k in FILING_KEYS }


def line_of( doc, run_file, backfilled=False ):
    """
    Flatten a result document to one history line.

    Requires:
        - doc has status, trigger and started_at; run_file is the result file's name
    Ensures:
        - returns the same keys for every run, a failed one included
        - a number the run could not measure is None
        - findings_by_commit counts findings per commit, under "unknown" for a finding with none
        - branch, owed, rate_limited, backoff_until and the usage of the run's judge calls (input, output, cache write and cache read tokens, notional cost, calls the SDK reported) are copied when the run measured them, else None
        - calls_per_hour is the judge calls over the elapsed time scaled to an hour, None for a run that made no call
    """
    window   = doc.get( "window" )
    found    = doc.get( "findings" )
    clusters = doc.get( "clusters" )
    by_commit = None
    if found is not None:
        by_commit = {}
        for f in found:
            sha            = f.get( "commit" ) or UNKNOWN_COMMIT
            by_commit[ sha ] = by_commit.get( sha, 0 ) + 1
    carried = doc.get( "carried" )
    usage   = doc.get( "usage" ) or { }
    calls   = doc.get( "judge_calls" )
    secs    = doc.get( "elapsed_seconds" )
    return { "schema_version": SCHEMA_VERSION, "run_file": run_file, "started_at": doc[ "started_at" ], "elapsed_seconds": doc.get( "elapsed_seconds" ),
             "trigger": doc[ "trigger" ], "mode": doc.get( "mode", MODE_DAILY ), "status": doc[ "status" ], "failure": failure_of( doc ),
             "window_start": window[ "start" ] if window else None, "window_end": window[ "end" ] if window else None, "commits": window[ "commits" ] if window else None,
             "judged": doc.get( "judged" ), "carried": len( carried ) if carried is not None else None, "cap": doc.get( "cap" ), "ceiling": doc.get( "ceiling" ),
             "judge_calls": doc.get( "judge_calls" ), "findings": len( found ) if found is not None else None, "groups": len( clusters ) if clusters is not None else None,
             "group_sizes": sorted( len( g ) for g in clusters ) if clusters is not None else None, "findings_by_commit": by_commit,
             **counts_of( doc.get( "filing" ) ), "unreadable": len( doc[ "unreadable" ] ) if doc.get( "unreadable" ) is not None else None, "backfilled": backfilled,
             "branch": doc.get( "branch" ), "owed": doc.get( "owed" ), "rate_limited": doc.get( "rate_limited" ), "backoff_until": doc.get( "backoff_until" ),
             "input_tokens": usage.get( "input_tokens" ), "output_tokens": usage.get( "output_tokens" ), "cache_creation_tokens": usage.get( "cache_creation_input_tokens" ),
             "cache_read_tokens": usage.get( "cache_read_input_tokens" ), "cost_usd": usage.get( "cost_usd" ), "usage_calls": usage.get( "calls" ),
             "calls_per_hour": round( calls / secs * 3600 ) if calls and secs else None }


def append_line( folder, line, name=RUNS_FILE ):
    """
    Append one line to runs.jsonl (or to the file called name), making the folder.

    Requires:
        - line is a dict of JSON values
    Ensures:
        - earlier lines are untouched
        - returns the path
    """
    path = pathlib.Path( folder ) / name
    path.parent.mkdir( parents=True, exist_ok=True )
    with path.open( "a", encoding="utf-8" ) as fh: fh.write( json.dumps( line, sort_keys=True ) + "\n" )
    return path


def read_history( folder ):
    """
    Read the history, oldest run first, and say which lines could not be read.

    Ensures:
        - returns { lines, bad }: lines are the readable history lines sorted by started_at, bad the 1-based numbers of the file's lines that are not a JSON object with an ISO-8601 started_at
        - the sort keeps file order between equal times, so a backfill after newer runs still reads in time order
        - a missing file gives no lines and no bad ones
    """
    path  = pathlib.Path( folder ) / RUNS_FILE
    found = []
    bad   = []
    for number, text in enumerate( path.read_text( encoding="utf-8" ).splitlines() if path.exists() else [], start=1 ):
        if not text.strip(): continue
        try:
            line = json.loads( text )
            when = datetime.datetime.fromisoformat( line[ "started_at" ] ).timestamp()
        except ( json.JSONDecodeError, TypeError, KeyError, ValueError ):
            bad.append( number )
            continue
        found.append( ( when, line ) )
    found.sort( key=lambda pair: pair[ 0 ] )
    return { "lines": [ line for _, line in found ], "bad": bad }


def read_lines( folder ):
    """Ensures: returns the readable history lines, oldest run first, or [] with no history."""
    return read_history( folder )[ "lines" ]


def backfill( folder ):
    """
    Add a line for each result file that has none, oldest first.

    Requires:
        - folder holds result files named <date>-<HHMMSS>-<trigger>.json
    Ensures:
        - a file already in the history, by name, is skipped, so a second call adds nothing
        - a file without started_at takes it from its name; every added line says backfilled
        - returns { added, skipped } as lists of file names
    """
    have  = { l[ "run_file" ] for l in read_lines( folder ) }
    out   = { "added": [], "skipped": [] }
    for path in sorted( pathlib.Path( folder ).glob( "*.json" ) ):
        if RUN_FILE.match( path.name ) is None: continue
        if path.name in have: out[ "skipped" ].append( path.name ); continue
        doc = json.loads( path.read_text( encoding="utf-8" ) )
        doc.setdefault( "started_at", started_from_name( path.name ) )
        append_line( folder, line_of( doc, path.name, backfilled=True ) )
        out[ "added" ].append( path.name )
    return out


def rising_run( lines, runs ):
    """
    Find a backlog that has grown for several daily runs in a row.

    Requires:
        - lines are history lines in time order; runs is a whole number, at least 1
    Ensures:
        - considers only daily runs that measured their carried count; failed runs and baseline runs are skipped, not counted as a fall
        - returns { runs, series } when the last runs steps each rose, series being the runs + 1 carried counts, oldest first
        - returns None otherwise, and when there are not enough measured runs
    """
    series = [ l[ "carried" ] for l in lines if l[ "mode" ] == MODE_DAILY and l[ "status" ] in MEASURED and l[ "carried" ] is not None ][ -( runs + 1 ): ]
    if len( series ) < runs + 1 or any( b <= a for a, b in zip( series, series[ 1: ] ) ): return None
    return { "runs": runs, "series": series }


def table( lines ):
    """
    Lay the series out as a table.

    Ensures:
        - returns the header and one row per line, columns padded to the widest cell, "-" for a value the run did not measure
        - started_at is shown to the minute
        - returns "no runs recorded" for an empty series
    """
    if not lines: return "no runs recorded"
    def cell( line, key ):
        """Ensures: returns the display text of one value."""
        v = line[ key ]
        if v is None: return "-"
        return v[ :16 ].replace( "T", " " ) if key == "started_at" else str( round( v ) if key == "elapsed_seconds" else v )
    rows  = [ [ head for _, head in TABLE_COLUMNS ], *[ [ cell( l, key ) for key, _ in TABLE_COLUMNS ] for l in lines ] ]
    width = [ max( len( r[ i ] ) for r in rows ) for i in range( len( TABLE_COLUMNS ) ) ]
    return "\n".join( "  ".join( c.rjust( w ) for c, w in zip( r, width ) ) for r in rows )


def main( argv=None, out=print ):
    """
    Print the run history or backfill it, from the command line.

    Requires:
        - argv holds at most one of --backfill and --table ( the default ), and optionally --folder
    Ensures:
        - --table prints the series, then the numbers of any unreadable lines it skipped; --backfill adds the missing lines and prints the file names it added
        - returns 0
    """
    ap = argparse.ArgumentParser( description="The run history of the daily duplicate check." )
    ap.add_argument( "--folder", default=None )
    ap.add_argument( "--backfill", action="store_true" )
    args   = ap.parse_args( argv )
    folder = args.folder or f"{chs.data_dir( cu.get_project_root() )}/{FOLDER}"
    if args.backfill:
        done = backfill( folder )
        out( f"added {len( done[ 'added' ] )}, skipped {len( done[ 'skipped' ] )}" )
        for name in done[ "added" ]: out( f"  {name}" )
        return 0
    read = read_history( folder )
    out( table( read[ "lines" ] ) )
    if read[ "bad" ]: out( f"skipped {len( read[ 'bad' ] )} unreadable line(s) of {RUNS_FILE}: {', '.join( str( n ) for n in read[ 'bad' ] )}" )
    return 0


if __name__ == "__main__":  # pragma: no cover - the entry only calls main
    sys.exit( main() )
