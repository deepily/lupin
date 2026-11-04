"""
The weekly fleet page of the reuse checks: lookups, outcome lines, refusals and audits.

The counts come from three places.
The call log shows what lookups were made. The file refusals.jsonl shows what each outcome line was and why it was refused.
The audit receipts of the shadow audit show the audits; the receipt's own flag tells known-miss from random-sample.
One report is one week: the seven calendar days that end on a given date, read in the host's time zone.
With no date given, the week is the last complete Monday-to-Sunday one, so pages follow one another with no lookup between them.
A record whose time cannot be read is left out of every count and listed on its own row, never guessed into a week.
The daily duplicate check has a table of its own: one row per run dated inside the week, then a total row.
It reads the result files of the check's folder.
The verdict on each finding comes from the finding itself, then from verdicts.jsonl beside the result files, then from its row in the task store.
A run with findings and no verdict at all shows "not triaged" in place of its counts.
A run with no findings is a row of zeros; a result file that cannot be read is counted under "Left out of the week".
No table has a column for a seat or a person; the page counts the fleet.
The tables are drawn by report_rollup.counts_table in its plain form. Nothing here sends anything or runs a model.

Exit 0 means the page was made. Exit 3 means it could not be: the date is not a date, a receipt is corrupt, or the page could not be written.
"""
import argparse
import datetime
import json
import pathlib
import re
import shlex
import sys

import cosa.utils.util as cu
from cosa.repo.symindex import librarian_tick as lt
from cosa.repo.symindex.candidates import shadow_audit as sa
from cosa.repo.symindex.candidates.errors import CandidateError
from lupin_mcp import duplicate_check_filing as ff
from lupin_mcp import reuse_exit_gate as eg
from lupin_mcp import reuse_outcome as ro
from lupin_mcp import reuse_refusals as rr
from lupin_mcp.reuse_needset.report_rollup import counts_table, share, table

WEEK_DAYS      = sa.WEEK_DAYS                                       # the days one report covers, the end date included
EXIT_NOT_MADE  = 3
AUDIT_ROWS     = ( "known-miss audits", "random-sample audits" )
UNDATED_ROW    = "left out: time not readable"
PAGE_FOLDER    = "reuse-behaviour"                                  # under the data folder; one file per end date
CRON_TAG       = "# reuse-behaviour-weekly"
CRON_SCHEDULE  = "0 18 * * *"                                       # every day at 18:00, an hour the host is on; the run skips when the last complete week's page is saved
BOOT_DELAY     = 360                                                # seconds after a boot, after the daily check's 300
CHECK_FOLDER   = "duplicate-check-daily"                            # under the data folder; the same folder duplicate_check_daily.FOLDER names
CHECK_NAME     = re.compile( r"^\d{4}-\d{2}-\d{2}-\d{6}-.+\.json$" )   # <date>-<time>-<trigger>.json; last-success.json does not match
VERDICT_LINE   = re.compile( r"\[amendment [^\]]*\]\s*VERDICT (DUPLICATE|EXTEND|DISTINCT)" )
REAL_VERDICTS  = ( "DUPLICATE", "EXTEND" )
NOT_VERDICTS   = ( "DISTINCT", )
CHECK_HEADERS  = ( "date", "trigger", "commits judged", "definitions judged", "judge calls", "minutes", "findings", "real duplicates", "not duplicates", "no verdict yet", "precision (real of ruled)" )
CHECK_TITLE    = "Daily duplicate check"
VERDICTS_FILE  = "verdicts.jsonl"                                   # beside the result files; duplicate_check_verdicts is its only writer
NOT_TRIAGED    = "not triaged"                                      # shown in place of a count when a run has findings and no verdict at all
BAD_CHECK_ROW  = "duplicate-check result files that cannot be read"
OUTCOME_KINDS  = ( "REUSED", "EXTENDED", "WROTE_NEW" )
UNPARSED       = "unparsed"
OTHER_REASON   = "other (not in this list)"
REASON_LABELS  = (                                                  # ( pattern, label ), in the order the report lists them
    ( r"does not match the REUSE-OUTCOME shape",       "line does not match the shape" ),
    ( r"^receipt \S+ is not in the log",              "receipt not in the log" ),
    ( r"^search \S+ is not in the log for receipt",   "search not in the log for the receipt" ),
    ( r"has no EXCLUDED_ refusal in the log",         "excluded with no logged refusal" ),
    ( r"goes in both id slots",                       "unindexed in only one id slot" ),
    ( r"in the search slot needs unindexed",          "unindexed search beside a real receipt" ),
    ( r"is a file the symbol index holds",            "unindexed file the index holds" ),
    ( r"has an outcome line and no ruling line",      "outcome line with no ruling line" ),
    ( r"^the outcome is \w+ but the ruling",          "outcome and ruling kinds disagree" ),
)


def read_refusals( data_dir ):
    """
    Read the records of refusals.jsonl.

    Requires:
        - data_dir is a directory
    Ensures:
        - returns the records in file order, one dict per line that is a JSON object
        - a missing file gives an empty list; a line that is not a JSON object is skipped, as the writer skips it
    """
    path = pathlib.Path( data_dir ) / rr.REFUSALS_NAME
    if not path.exists(): return []
    out = []
    for raw in path.read_text( encoding="utf-8" ).splitlines():
        try: row = json.loads( raw )
        except ValueError: continue
        if isinstance( row, dict ): out.append( row )
    return out


def reason_label( reason ):
    """Ensures: returns the label of the first pattern the reason matches, or OTHER_REASON."""
    return next( ( label for pattern, label in REASON_LABELS if re.search( pattern, reason ) ), OTHER_REASON )


def count_lookups( records ):
    """
    Count the lookup calls in the call log.

    Requires:
        - records is what merge_call_logs returns
    Ensures:
        - returns { name: count } in a fixed order: one entry per lookup tool for calls that logged no error, then the lookups that failed
        - every call counts, so the same need looked up twice is two lookups
    """
    calls = [ r for r in records if r.get( "tool" ) in eg.RECEIPT_TOOLS ]
    out   = { tool: sum( 1 for r in calls if r[ "tool" ] == tool and not r.get( "error" ) ) for tool in eg.RECEIPT_TOOLS }
    out[ "failed (any lookup tool)" ] = sum( 1 for r in calls if r.get( "error" ) )
    return out


def count_outcomes( rows ):
    """
    Count the scanned outcome lines by kind.

    Requires:
        - rows is what read_refusals returns
    Ensures:
        - returns { kind: count } for `REUSED`, `EXTENDED` and `WROTE_NEW` in that order, then `unparsed` for a line off the shape
        - each record counts once
    """
    out = { kind: 0 for kind in OUTCOME_KINDS } | { UNPARSED: 0 }
    for row in rows:
        parsed = ro.parse_outcomes( row.get( "line", "" ) )
        out[ parsed[ 0 ][ "outcome" ] if parsed else UNPARSED ] += 1
    return out


def count_refusals( rows ):
    """
    Count the refusals by reason.

    Requires:
        - rows is what read_refusals returns
    Ensures:
        - returns { label: count } with every label in REASON_LABELS in order, zeros included, then the other row
        - a refused record with two reasons counts under each
        - an accepted record counts nowhere here
    """
    out = { label: 0 for _, label in REASON_LABELS } | { OTHER_REASON: 0 }
    for row in rows:
        for reason in row.get( "reasons", [] ): out[ reason_label( reason ) ] += 1
    return out


def report( records, rows ):
    """
    Render the behaviour report in its plain form.

    Requires:
        - records is what merge_call_logs returns; rows is what read_refusals returns
    Ensures:
        - returns four counts tables joined by a blank line: lookups, scanned lines by status, outcome lines by kind, refusals by reason
    """
    status = { "accepted": sum( 1 for r in rows if r.get( "status" ) == "accepted" ), "refused": sum( 1 for r in rows if r.get( "status" ) == "refused" ) }
    return "\n\n".join( [ counts_table( "Lookups", count_lookups( records ) ), counts_table( "Scanned outcome lines", status ),
                          counts_table( "Outcome lines by kind", count_outcomes( rows ) ), counts_table( "Refusals by reason", count_refusals( rows ) ) ] )


def local_tz():
    """Ensures: returns the host's current time zone."""
    return datetime.datetime.now().astimezone().tzinfo


def week_of( end ):
    """
    Name the seven days that end on a date.

    Requires:
        - end is an ISO date text or a date
    Ensures:
        - returns ( first day, last day ) as dates; the last day is end and the first is six days before it
    Raises:
        - ValueError when end is not an ISO date
    """
    last = end if isinstance( end, datetime.date ) else datetime.date.fromisoformat( end )
    return last - datetime.timedelta( days=WEEK_DAYS - 1 ), last


def last_complete_week_end( today ):
    """
    Name the Sunday that closes the last complete Monday-to-Sunday week.

    Requires:
        - today is a date
    Ensures:
        - returns the latest Sunday before today, so a Sunday is not its own week's end: that week is not over until the day ends
        - every day from one Monday to the next Sunday gives the same answer, so a boot on any of them reports the week the cron run reports
    """
    return today - datetime.timedelta( days=( today.weekday() + 1 ) % 7 or 7 )


def day_of( stamp, tz ):
    """
    Read the calendar day of an ISO time stamp in a time zone.

    Requires:
        - tz is a tzinfo
    Ensures:
        - returns the date of the stamp in tz, or None when the stamp is not text, not an ISO time, or has no offset
    """
    if not isinstance( stamp, str ): return None
    try: moment = datetime.datetime.fromisoformat( stamp )
    except ValueError: return None
    return moment.astimezone( tz ).date() if moment.tzinfo is not None else None


def in_week( items, key, week, tz ):
    """
    Split items into those dated inside the week and those with no readable date.

    Requires:
        - items are dicts; key names the time stamp field; week is week_of's answer
    Ensures:
        - returns ( kept, undated ): kept are the items whose stamp falls in the week, in order; undated are those whose stamp cannot be read
        - an item dated outside the week is in neither
    """
    kept, undated = [], []
    for item in items:
        day = day_of( item.get( key ), tz )
        if day is None: undated.append( item )
        elif week[ 0 ] <= day <= week[ 1 ]: kept.append( item )
    return kept, undated


def count_audits( receipts, week ):
    """
    Count the audit receipts of the week, told apart by the receipt's known-miss flag.

    Requires:
        - receipts is what shadow_audit.load_receipts returns; week is week_of's answer
    Ensures:
        - returns { "known-miss audits": n, "random-sample audits": m } for receipts whose audited_on falls in the week
        - a receipt dated outside the week counts nowhere
    """
    held = [ r for r in receipts if week[ 0 ] <= datetime.date.fromisoformat( r[ "audited_on" ] ) <= week[ 1 ] ]
    return { AUDIT_ROWS[ 0 ]: sum( 1 for r in held if r[ sa.NEW_FIELD ] ), AUDIT_ROWS[ 1 ]: sum( 1 for r in held if not r[ sa.NEW_FIELD ] ) }


def read_check_run( path ):
    """
    Read one result file of the daily duplicate check.

    Requires:
        - path is a file named like <date>-<time>-<trigger>.json
    Ensures:
        - returns { day, trigger, stem, commits, judged, calls, seconds, findings } where findings is a list of ( verdict field or None, correlation key or None, finding id or None )
        - stem is the file name without `.json`, the `run=` of a verdict line
        - commits is the window's commit count, 0 for a run with no window; judged is the number of definitions judged
        - a run that judged nothing, or never reached judging, has judged 0 and no findings
        - returns None when the file cannot be read, is not a JSON object, or lacks a readable date, trigger, judge_calls or elapsed_seconds
    """
    try:
        doc = json.loads( path.read_text( encoding="utf-8" ) )
        return { "day": datetime.date.fromisoformat( doc[ "date" ] ), "trigger": str( doc[ "trigger" ] ), "stem": path.stem, "commits": int( doc.get( "window", { } ).get( "commits", 0 ) ), "judged": int( doc.get( "judged", 0 ) ), "calls": int( doc[ "judge_calls" ] ),
                 "seconds": float( doc[ "elapsed_seconds" ] ), "findings": [ ( f.get( "verdict" ), f.get( "correlation_key" ), f.get( "id" ) ) for f in doc.get( "findings", [] ) ] }
    except ( OSError, ValueError, KeyError, TypeError, AttributeError ):
        return None


def read_check_runs( folder, week ):
    """
    Read the result files of the week.

    Requires:
        - week is week_of's answer
    Ensures:
        - returns ( runs, unreadable ): runs are the read_check_run answers dated inside the week, oldest file name first; unreadable is the count of files that could not be read
        - a missing folder gives ( [], 0 ); a file whose name is not a result file's, such as last-success.json, is not read
        - a readable run dated outside the week is in neither
    """
    folder = pathlib.Path( folder )
    if not folder.is_dir(): return [], 0
    read = [ read_check_run( p ) for p in sorted( folder.glob( "*.json" ) ) if CHECK_NAME.match( p.name ) ]
    return [ r for r in read if r is not None and week[ 0 ] <= r[ "day" ] <= week[ 1 ] ], sum( 1 for r in read if r is None )


def read_verdicts( folder ):
    """
    Read the verdict lines the triage seat logged, as the writer saved them.

    Requires:
        - folder is the check's result folder; the file is VERDICTS_FILE inside it
    Ensures:
        - returns { ( run, finding ): verdict }, the last line for a pair winning
        - a missing file is an empty answer
    Raises:
        - ValueError naming the line when a line is not a JSON object with a run, a finding and a known verdict
    """
    path = pathlib.Path( folder ) / VERDICTS_FILE
    if not path.is_file(): return { }
    got = { }
    for n, text in enumerate( path.read_text( encoding="utf-8" ).splitlines(), 1 ):
        try:
            rec = json.loads( text )
            if rec[ "verdict" ] not in REAL_VERDICTS + NOT_VERDICTS: raise ValueError( "unknown verdict" )
            got[ ( rec[ "run" ], rec[ "finding" ] ) ] = rec[ "verdict" ]
        except ( ValueError, KeyError, TypeError ) as e:
            raise ValueError( f"{VERDICTS_FILE} line {n} is not a verdict record: {type( e ).__name__}: {e}" ) from e
    return got


def verdict_of( field, key, store, logged=None ):
    """
    Name the crew's verdict on one finding.

    Requires:
        - field is the finding's own verdict, or None; key is its correlation key, or None
        - store has query( key ) returning ( ok, status, body ), or is None
        - logged is the verdict read_verdicts holds for the finding, or None
    Ensures:
        - returns `duplicate`, `extend` or `distinct` in capitals, taken from the finding's own verdict field when it holds one, whatever the case
        - otherwise returns logged, when there is one; the log is read from a file, so it costs no store read
        - otherwise returns the word of the last `VERDICT <word>` in the row's amendments in the store
        - returns None when there is no key, no store, a read that did not answer ok, or no verdict yet
    """
    if isinstance( field, str ) and field.upper() in REAL_VERDICTS + NOT_VERDICTS: return field.upper()
    if logged is not None: return logged
    if store is None or key is None: return None
    ok, _status, body = store.query( key )
    if not ok: return None
    found = [ w for task in body.get( "tasks", [] ) for w in VERDICT_LINE.findall( task.get( "body", "" ) ) ]
    return found[ -1 ] if found else None


def check_counts( run, store, logged=None ):
    """
    Count one run's findings by verdict.

    Requires:
        - logged is read_verdicts' answer, or None for no log
    Ensures:
        - returns { real, not_dup, open } that add up to the run's findings; open are the findings with no verdict yet
        - a finding is looked up in the log by the run's stem and its own id
    """
    logged   = logged if logged is not None else { }
    verdicts = [ verdict_of( field, key, store, logged.get( ( run[ "stem" ], fid ) ) ) for field, key, fid in run[ "findings" ] ]
    real     = sum( 1 for v in verdicts if v in REAL_VERDICTS )
    not_dup  = sum( 1 for v in verdicts if v in NOT_VERDICTS )
    return { "real": real, "not_dup": not_dup, "open": len( verdicts ) - real - not_dup }


def ruled_cells( findings, real, not_dup ):
    """
    Name the three cells that depend on the verdicts: real, not, precision.

    Ensures:
        - returns ( real, not, precision ) as the page shows them
        - findings with no verdict at all give NOT_TRIAGED in all three, never 0: nobody has looked, which is not the same as none being real
        - no findings, or at least one verdict, gives the counts and share's precision
    """
    if findings > 0 and real + not_dup == 0: return NOT_TRIAGED, NOT_TRIAGED, NOT_TRIAGED
    return real, not_dup, share( real, real + not_dup )


def check_table( runs, store, logged=None ):
    """
    Draw the daily duplicate check table.

    Requires:
        - runs are read_check_runs' answer; logged is read_verdicts' answer, or None
    Ensures:
        - returns CHECK_TITLE, then a table with one row per run in the given order and a last row `total`
        - a run with no findings is a row of zeros
        - a run with findings and no verdict shows `not triaged` for real, not and precision, never 0; so does the total row when that holds for every finding
        - precision is real duplicates out of those ruled, real plus not; findings with no verdict are in their own column and in neither side
        - the total row sums every column, and its precision is the sum's, not an average of the rows'
    """
    rows, sums = [], { "commits": 0, "judged": 0, "calls": 0, "seconds": 0.0, "findings": 0, "real": 0, "not_dup": 0, "open": 0 }
    for run in runs:
        got  = check_counts( run, store, logged ) | { "commits": run[ "commits" ], "judged": run[ "judged" ], "calls": run[ "calls" ], "seconds": run[ "seconds" ], "findings": len( run[ "findings" ] ) }
        for k in sums: sums[ k ] += got[ k ]
        real, not_dup, precision = ruled_cells( got[ "findings" ], got[ "real" ], got[ "not_dup" ] )
        rows.append( [ run[ "day" ].isoformat(), run[ "trigger" ], got[ "commits" ], got[ "judged" ], got[ "calls" ], f"{got[ 'seconds' ] / 60:.1f}", got[ "findings" ], real, not_dup, got[ "open" ], precision ] )
    real, not_dup, precision = ruled_cells( sums[ "findings" ], sums[ "real" ], sums[ "not_dup" ] )
    rows.append( [ "total", "", sums[ "commits" ], sums[ "judged" ], sums[ "calls" ], f"{sums[ 'seconds' ] / 60:.1f}", sums[ "findings" ], real, not_dup, sums[ "open" ], precision ] )
    return CHECK_TITLE + "\n\n" + table( list( CHECK_HEADERS ), rows )


def weekly_report( records, rows, receipts, end, tz=None, check_dir=None, store=None ):
    """
    Render the week that ends on a date.

    Requires:
        - records is what merge_call_logs returns; rows is what read_refusals returns; receipts is what load_receipts returns
        - end is an ISO date text or a date; tz is a tzinfo, or None for the host's
        - check_dir is the folder of the daily duplicate check's result files, or None for a page with no such table
        - store is verdict_of's store; it is read only when a finding in the week has no verdict field and no line in verdicts.jsonl
    Ensures:
        - with a check_dir, the audits are followed by check_table's table, and unreadable result files are counted in the left-out table's last row
        - returns a title line naming the seven days, then the tables of report, then the audits table, joined by blank lines
        - only records and refusal rows dated inside the week are counted
        - when any record has no readable time, a last table counts them, under one row per source
    """
    tz            = tz if tz is not None else local_tz()
    week          = week_of( end )
    calls, no_ts  = in_week( records, "ts", week, tz )
    kept, no_at   = in_week( rows, "at", week, tz )
    title         = f"Reuse behaviour, {week[ 0 ].isoformat()} to {week[ 1 ].isoformat()} (seven days, the whole fleet, no seat named)"
    parts         = [ title, report( calls, kept ), counts_table( "Audits", count_audits( receipts, week ) ) ]
    left_out      = { "call log records with no readable time": len( no_ts ), "outcome records with no readable time": len( no_at ) }
    bad_files     = 0
    if check_dir is not None:
        runs, bad_files = read_check_runs( check_dir, week )
        parts.append( check_table( runs, store, read_verdicts( check_dir ) ) )
        left_out[ BAD_CHECK_ROW ] = bad_files
    if no_ts or no_at or bad_files: parts.append( counts_table( "Left out of the week", left_out ) )
    return "\n\n".join( parts )


def cron_lines( root, python, log_path, carried=None ):
    """
    Build the two cron lines of the weekly page.

    Requires:
        - root is the main checkout path; python is the interpreter path
        - carried maps environment names to values, copied into both lines and shell-quoted
    Ensures:
        - returns [ weekly line, reboot line ], each ending with CRON_TAG
        - the first line runs daily at CRON_SCHEDULE; the reboot line BOOT_DELAY seconds after a boot, so a day the host slept through is made up at the next boot
        - both read the same week and write the same file, because the page's default end date is the same on every day of one week
        - both run from root with LUPIN_ROOT and PYTHONPATH set, write the page with --write --skip-if-saved and append to log_path
        - so the page is made on the first run after its week closes, and every later run skips
    """
    extra = "".join( f"{name}={shlex.quote( value )} " for name, value in ( carried or {} ).items() )
    run   = f"cd {root} && LUPIN_ROOT={root} PYTHONPATH={root}/src {extra}{python} -m lupin_mcp.reuse_behaviour --write --skip-if-saved >> {log_path} 2>&1 {CRON_TAG}"
    return lt.cron_lines_for( run, CRON_SCHEDULE, BOOT_DELAY )


def main( argv=None, out=None, store=None ):
    """
    Run the weekly page from the command line.

    Ensures:
        - prints the weekly page for the seven days that end on --end, which defaults to the last complete week's Sunday
        - --data-dir holds refusals.jsonl, the receipts folder and, unless --log-dir says otherwise, the call-log folder; it defaults to the lookup tools' choice
        - --write also saves the page as <data dir>/reuse-behaviour/reuse-behaviour-<end>.txt, replacing that day's file
        - --skip-if-saved, with --write, makes no page and prints one line saying so when that file already exists and is not empty; it returns 0
        - --print-cron prints the two cron lines and nothing else; it installs nothing
        - the page carries the daily duplicate check table from <data dir>/duplicate-check-daily, or from --check-dir; verdicts come from the finding, then verdicts.jsonl in that folder, then the task store (unless store is given)
        - returns 0 when the page was made, 3 with the reason printed when it could not be
    """
    ap = argparse.ArgumentParser( description="The weekly fleet page of the reuse checks." )
    ap.add_argument( "--end", default=None, help="the last of the seven days, as YYYY-MM-DD; default is the Sunday that closes the last complete week" )
    ap.add_argument( "--data-dir", default=None )
    ap.add_argument( "--log-dir", default=None, help="the call log folder; default is <data dir>/call-log" )
    ap.add_argument( "--check-dir", default=None, help="the daily duplicate check's result folder; default is <data dir>/duplicate-check-daily" )
    ap.add_argument( "--write", action="store_true", help="also save the page under the data folder" )
    ap.add_argument( "--skip-if-saved", action="store_true", help="with --write: do nothing when the page for the end date is already saved" )
    ap.add_argument( "--print-cron", action="store_true", help="print the weekly and reboot cron lines" )
    ap.add_argument( "--log-path", default=None, help="the file the cron lines append to; needed with --print-cron" )
    ap.add_argument( "--python", default=sys.executable )
    a    = ap.parse_args( argv )
    if a.skip_if_saved and not a.write: ap.error( "--skip-if-saved needs --write" )
    out  = out if out is not None else sys.stdout
    root = cu.get_project_root()
    if a.print_cron:
        if a.log_path is None:
            print( "REFUSING: --print-cron needs --log-path. Nothing was made.", file=out )
            return EXIT_NOT_MADE
        print( "\n".join( cron_lines( root, a.python, a.log_path ) ), file=out )
        return 0
    try:
        end   = a.end if a.end is not None else last_complete_week_end( datetime.datetime.now().astimezone().date() ).isoformat()
        end   = week_of( end )[ 1 ].isoformat()
        data  = pathlib.Path( a.data_dir or rr.default_data_dir( root ) )
        saved = data / PAGE_FOLDER / f"reuse-behaviour-{end}.txt"
        if a.skip_if_saved and saved.is_file() and saved.stat().st_size > 0:
            print( f"SKIPPED: the page for {end} is already saved at {saved}.", file=out )
            return 0
        records, _bad = eg.merge_call_logs( a.log_dir or data / "call-log" )
        page  = weekly_report( records, read_refusals( data ), sa.load_receipts( data ), end, check_dir=a.check_dir or data / CHECK_FOLDER, store=store if store is not None else ff.LiveStore() )
        if a.write:
            saved.parent.mkdir( parents=True, exist_ok=True )
            saved.write_text( page + "\n", encoding="utf-8" )
    except ( OSError, ValueError, CandidateError ) as e:
        print( f"REFUSING: {type( e ).__name__}: {e}. Nothing was made.", file=out )
        return EXIT_NOT_MADE
    print( page, file=out )
    return 0


if __name__ == "__main__":  # pragma: no cover - thin process entry, main() is tested
    sys.exit( main() )
