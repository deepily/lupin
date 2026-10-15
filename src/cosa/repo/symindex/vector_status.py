"""
Say whether the stored vector set is stale, and file a store row when it is.

The check reads four things and builds nothing. They are the set's build info, the index generation
published now, the stored purpose lines and the daily job's state file. It writes one status file
in the job's folder. When the answer is stale it asks the librarian for one store row, so a missed
day is owed and not silent. The daily librarian tick runs it and carries the verdict on its report.
The command line here runs it alone and files nothing.

Design: section 5.5 of the reuse vector store freshness design.

Exit 0 means the set is fresh.
Exit 1 means the set is stale.
"""
import argparse
import datetime
import json
import os
import sys

from cosa.repo.symindex import build as sx_build
from cosa.repo.symindex import librarian_tick as lt
from cosa.repo.symindex import vector_refresh as vr
from cosa.repo.symindex.candidates import freshness as fr
from cosa.repo.symindex.candidates import purpose_lines as pl
from cosa.repo.symindex.candidates import storage_paths as sp
from cosa.repo.symindex.paths import data_dir, default_out_dir

STALE_HOURS_KEY     = "reuse vector stale hours"
DEFAULT_STALE_HOURS = 36.0
STATUS_NAME         = "vector-status.json"
STALE_TITLE         = "[LUPIN] reuse vector set is stale"
EXIT_FRESH          = 0
EXIT_STALE          = 1


def read_stale_hours( reader=None ):
    """
    Read how old a set may be before it is stale.

    Requires:
        - reader is a callable ( key ) returning a string or None, or None for the live disk reader

    Ensures:
        - returns the configured number of hours when it parses as a positive number
        - otherwise returns DEFAULT_STALE_HOURS
        - never raises
    """
    raw = ( lt._disk_value( STALE_HOURS_KEY, reader ) or "" ).strip()
    try:
        hours = float( raw )
    except ValueError:
        return DEFAULT_STALE_HOURS
    return hours if hours > 0 else DEFAULT_STALE_HOURS


def age_hours( built_at, now ):
    """
    Measure how long ago a set was built.

    Requires:
        - built_at is the ISO string from build-info.json
        - now is a datetime, naive local time or aware

    Ensures:
        - returns the age in hours, rounded to two places
        - returns None when built_at is not an ISO time with an offset
    """
    try:
        built = datetime.datetime.fromisoformat( built_at )
    except ( TypeError, ValueError ):
        return None
    if built.tzinfo is None: return None
    return round( ( now.astimezone( datetime.timezone.utc ) - built.astimezone( datetime.timezone.utc ) ).total_seconds() / 3600, 2 )


def compute( root, now, stale_hours=DEFAULT_STALE_HOURS, config=None, environ=None, screen=None ):
    """
    Read the freshness facts and decide.

    Requires:
        - root is the main checkout
        - now is a datetime in local time

    Ensures:
        - returns a dict with stale, reasons, built_at, age_hours, set_index_manifest, current_index_manifest,
          index_differs, missing_purpose_lines, job_due and the last_* fields of the job's state file
        - builds nothing: an index that is not published leaves its fields None and never counts against the set
        - stale is True when the set has no build info, its time cannot be read, it is older than stale_hours,
          or the index changed since it was built and the daily job is not due
        - a set with no build info is stale, never fresh, as read_build_info says
        - reasons names every condition that held, in that order
    """
    data    = data_dir( root )
    live    = sp.candidate_dir( "vectors", data, config, environ )
    state   = lt.read_state( os.path.join( vr.refresh_dir( root ), vr.STATE_NAME ) )
    info    = fr.read_build_info( live )
    gen     = sx_build.current_generation( default_out_dir( root ) )
    current = fr.index_manifest( sx_build.read_header( gen ) ) if gen is not None else None
    missing = None
    if gen is not None:
        screen  = screen if screen is not None else pl.default_screen()
        settled = info.get( "unwritten_pins", [] ) if info is not None and info[ "index_manifest" ] == current else []
        missing = vr.missing_purpose_lines( sx_build.read_symbols( gen ), sp.candidate_dir( "purpose", data, config, environ ) / "purpose.jsonl", screen, settled )
    built_at  = info[ "built_at" ] if info is not None else None
    age       = age_hours( built_at, now ) if info is not None else None
    differs   = info is not None and current is not None and info[ "index_manifest" ] != current
    job_due   = lt.due( now, state )
    reasons   = []
    if info is None: reasons.append( "the set has no build info" )
    elif age is None: reasons.append( f"the set's build time cannot be read: {built_at}" )
    elif age > stale_hours: reasons.append( f"the set is {age} hours old, over {stale_hours}" )
    if differs and not job_due: reasons.append( "the index changed since the set was built and the daily job has already run today" )
    return { "checked_at": now.isoformat( timespec="seconds" ), "stale": bool( reasons ), "reasons": reasons, "stale_after_hours": stale_hours,
             "built_at": built_at, "age_hours": age, "set_index_manifest": info[ "index_manifest" ] if info is not None else None,
             "current_index_manifest": current, "index_differs": differs, "missing_purpose_lines": missing, "job_due": job_due,
             **{ k: state.get( k ) for k in ( "last_outcome", "last_seconds", "last_error", "last_attempt_at", "last_run_date" ) } }


def stale_row( status ):
    """
    Build the title and body of the store row for a stale set.

    Requires:
        - status is a dict compute returned with stale True

    Ensures:
        - returns ( STALE_TITLE, body ); the title never changes, so one open row stands for the condition
        - the body names every reason, the numbers, the job's last outcome and the command that rebuilds
    """
    lines = [ "The stored reuse vector set is stale.", "" ]
    lines += [ f"- {reason}" for reason in status[ "reasons" ] ]
    lines += [ "", f"built_at: {status[ 'built_at' ]}", f"age_hours: {status[ 'age_hours' ]}",
               f"index_differs: {status[ 'index_differs' ]}", f"pins_without_purpose_line: {status[ 'missing_purpose_lines' ]}",
               f"last_outcome: {status[ 'last_outcome' ]}", f"last_error: {status[ 'last_error' ]}",
               f"last_attempt_at: {status[ 'last_attempt_at' ]}", f"checked_at: {status[ 'checked_at' ]}", "",
               "Rebuild: python -m cosa.repo.symindex.vector_refresh --force",
               "Close this row once a fresh set is in the shared vectors folder." ]
    return STALE_TITLE, "\n".join( lines )


def check( root, now, librarian=None, stale_hours=None, config=None, environ=None, screen=None, log=print ):
    """
    Run the check, write the status file and file the row when stale.

    Requires:
        - librarian is a Librarian with hold_or_create, or None to file nothing

    Ensures:
        - returns the status dict, with row set to "exists", "created", "pending" or "unreadable" when a row was asked for
        - the status file in the job's folder holds the same dict
        - a store that cannot be read is logged, leaves row "unreadable" and does not raise
        - a fresh set files nothing and leaves any open row for a person to close
    """
    hours  = stale_hours if stale_hours is not None else read_stale_hours()
    status = compute( root, now, hours, config, environ, screen )
    if status[ "stale" ] and librarian is not None:
        title, body = stale_row( status )
        try:
            status[ "row" ] = librarian.hold_or_create( title, body )
        except RuntimeError as error:
            log( f"vector status: the store could not be read, so no stale row was filed: {error}" )
            status[ "row" ] = "unreadable"
    lt.write_state( os.path.join( vr.refresh_dir( root ), STATUS_NAME ), status )
    return status


def main( argv=None, environ=None, now=None, out=sys.stdout ):
    """
    Run the command line.

    Ensures:
        - prints the status as JSON, files no row and returns EXIT_FRESH or EXIT_STALE
        - writes the status file, as check does
    """
    environ = os.environ if environ is None else environ
    parser  = argparse.ArgumentParser( prog="python -m cosa.repo.symindex.vector_status", description=__doc__.split( "\n\n" )[ 0 ] )
    parser.add_argument( "--root" )
    args    = parser.parse_args( argv )
    root    = args.root or environ.get( "LUPIN_ROOT" ) or os.getcwd()
    status  = check( root, now or datetime.datetime.now(), environ=environ )
    print( json.dumps( status, sort_keys=True ), file=out )
    return EXIT_STALE if status[ "stale" ] else EXIT_FRESH


if __name__ == "__main__":  # pragma: no cover - process entry point
    sys.exit( main() )
