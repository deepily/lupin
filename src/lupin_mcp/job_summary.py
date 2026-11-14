"""
The shared writer of the job-summary/1 record a job leaves after every run.

One small file per job, rewritten whole by rename, so a reader never sees half a file. The record carries two debts
(work not yet looked at, rows filed and still open) and two times (last attempt, last finished run).
It carries no health field. The reader computes health from the registry, this record and the clock,
because a dead job cannot write "I am dead". Null means "not reported", never zero. Design: planning-is-prompting
src/rnd/2026.11.07-background-job-reporting-format.md section 1.
"""
import datetime
import json
import os
import pathlib
import sys

from cosa.utils.atomic_json import write_json_atomic

SCHEMA          = "job-summary/1"
MAX_POINTS      = 14
OUTCOMES        = ( "clean", "carried", "failed", "skipped", "disabled" )     # disabled: the job's INI switch was off, so the run did nothing
FINISHED        = ( "clean", "carried" )                              # outcomes that count as "ran to the end"
TRIGGERS        = ( "cron", "boot", "hand" )
ATTEMPT_KEYS    = ( "started_at", "finished_at", "trigger", "outcome", "stage", "failure", "evidence", "mode" )
MAX_RECENT      = 7
TRIGGER_ENV     = "LUPIN_JOB_TRIGGER"                                 # set to "hand" by the Run now endpoint
SCAN_KEYS       = ( "unit", "count", "never_checked", "drained_last_run", "arrived_last_interval", "freshness" )
FIX_KEYS        = ( "unit", "own_mark", "unfiled", "opened_in_run", "kind", "open_reported" )


def iso_now( now=None ):
    """
    Format a time, or the current local time, as ISO-8601 with an offset, to the second.

    Requires:
        - now is None or a timezone-aware datetime
    Ensures:
        - returns the string form
    """
    if now is None: now = datetime.datetime.now().astimezone()
    return now.replace( microsecond=0 ).isoformat()


def read_summary( path ):
    """
    Read a summary file.

    Requires:
        - path names a file or nothing
    Ensures:
        - returns the parsed record, or None when the file is missing, unreadable or not a record of this schema
    """
    try:
        doc = json.loads( pathlib.Path( path ).read_text() )
    except ( OSError, ValueError ):
        return None
    return doc if isinstance( doc, dict ) and doc.get( "schema" ) == SCHEMA else None


def check_attempt( attempt ):
    """
    Check an attempt against the record's rules.

    Requires:
        - attempt is a dict
    Ensures:
        - returns the attempt with every key in ATTEMPT_KEYS present, absent ones None
    Raises:
        - ValueError when the outcome or trigger is not one of the listed values, or a start time is missing
    """
    if attempt.get( "outcome" ) not in OUTCOMES: raise ValueError( f"outcome must be one of {OUTCOMES}, got {attempt.get( 'outcome' )!r}" )
    if attempt.get( "trigger" ) not in TRIGGERS: raise ValueError( f"trigger must be one of {TRIGGERS}, got {attempt.get( 'trigger' )!r}" )
    if not attempt.get( "started_at" ): raise ValueError( "an attempt needs a started_at" )
    return { key: attempt.get( key ) for key in ATTEMPT_KEYS }


def trigger_from_env( default, environ=None ):
    """
    Say how this run was started.

    Requires:
        - default is one of the listed triggers (cron, boot, hand)
    Ensures:
        - returns the value of LUPIN_JOB_TRIGGER when it names a trigger (Run now sets it to hand), else default
    """
    value = ( os.environ if environ is None else environ ).get( TRIGGER_ENV )
    return value if value in TRIGGERS else default


def trimmed( points ):
    """Ensures: returns the newest MAX_POINTS entries of points."""
    return points[ -MAX_POINTS: ]


def scan_block( given, previous, attempt, as_of ):
    """
    Build the scan-debt block.

    Requires:
        - given is a dict of SCAN_KEYS entries, or None when the job has no scan debt to report this run
        - previous is the block of the last record, or None
    Ensures:
        - a run that gave no block, or did not finish, returns the previous block (None when there is none)
        - a failed, skipped or disabled run carries the previous block forward with its old as_of: the count is stale, not zero
        - a finished run gets a new as_of and appends one point when it reported a count
        - a job whose count fell gets drained = max( reported, the fall ): 168 to 3 drained 165, and 24 to 2 with a reported 10 drained 22, so arrived can never be negative (a job whose debt others clear reports 0 or too little)
        - a reported figure above the fall is kept, and none stays none when the count did not fall, because a missing figure is not a zero
        - arrived_last_interval is derived (count now - count before + drained) only when the job left it null and a previous count exists
    """
    if given is None or attempt[ "outcome" ] not in FINISHED: return previous
    block  = { key: given.get( key ) for key in SCAN_KEYS }
    points = list( previous[ "points" ] ) if previous is not None else []
    if block[ "count" ] is not None and points and points[ -1 ][ "count" ] is not None and points[ -1 ][ "count" ] > block[ "count" ]:
        block[ "drained_last_run" ] = max( block[ "drained_last_run" ] or 0, points[ -1 ][ "count" ] - block[ "count" ] )
    if block[ "arrived_last_interval" ] is None and block[ "count" ] is not None and block[ "drained_last_run" ] is not None and points:
        block[ "arrived_last_interval" ] = block[ "count" ] - points[ -1 ][ "count" ] + block[ "drained_last_run" ]
    if block[ "count" ] is not None: points.append( { "at": as_of, "count": block[ "count" ], "drained": block[ "drained_last_run" ] } )
    block[ "as_of" ]  = as_of
    block[ "points" ] = trimmed( points )
    return block


def fix_block( given, previous, attempt, as_of ):
    """
    Build the fix-debt block.

    Requires:
        - given is a dict of FIX_KEYS entries, or None
        - previous is the block of the last record, or None
    Ensures:
        - a run that gave no block, or did not finish, returns the previous block (None when there is none)
        - a failed, skipped or disabled run carries the previous block forward unchanged
        - a finished run appends one point whose opened_total is the previous total plus opened_in_run
    """
    if given is None or attempt[ "outcome" ] not in FINISHED: return previous
    block  = { key: given.get( key ) for key in FIX_KEYS }
    if block[ "kind" ] is None: block[ "kind" ] = "rows"
    points = list( previous[ "points" ] ) if previous is not None else []
    if block[ "opened_in_run" ] is not None:
        before = points[ -1 ][ "opened_total" ] if points else 0
        points.append( { "at": as_of, "opened_total": before + block[ "opened_in_run" ] } )
    block[ "points" ] = trimmed( points )
    return block


def build_summary( job, attempt, scan_debt=None, fix_debt=None, previous=None, work_found_last_run=None, now=None, target=None ):
    """
    Build the next record from this run and the last record.

    Requires:
        - job is the registry's job id
        - attempt passes check_attempt
        - previous is the last record of this job (and target), or None
    Ensures:
        - returns a dict with schema job-summary/1 and no health field
        - recent holds the last MAX_RECENT attempts as { at, outcome, mode }, oldest first
        - last_finished moves only on a clean or carried attempt
        - consecutive_failures grows on failed, resets on clean or carried, and holds on skipped and disabled
        - work_found_last_run holds its previous value on a failed, skipped or disabled run
    Raises:
        - ValueError from check_attempt
    """
    attempt = check_attempt( attempt )
    written = iso_now( now )
    as_of   = attempt[ "finished_at" ] or written
    prev    = previous or {}
    if attempt[ "outcome" ] in FINISHED:
        last_finished = { "started_at": attempt[ "started_at" ], "outcome": attempt[ "outcome" ], "evidence": attempt[ "evidence" ] }
        failures      = 0
        found         = work_found_last_run
    else:
        last_finished = prev.get( "last_finished" )
        failures      = prev.get( "consecutive_failures", 0 ) + ( 1 if attempt[ "outcome" ] == "failed" else 0 )
        found         = prev.get( "work_found_last_run" )
    recent = list( prev.get( "recent" ) or [] ) + [ { "at": attempt[ "started_at" ], "outcome": attempt[ "outcome" ], "mode": attempt[ "mode" ] } ]
    return {
        "schema"               : SCHEMA,
        "job"                  : job,
        "target"               : target,
        "written_at"           : written,
        "last_attempt"         : attempt,
        "last_finished"        : last_finished,
        "consecutive_failures" : failures,
        "work_found_last_run"  : found,
        "scan_debt"            : scan_block( scan_debt, prev.get( "scan_debt" ), attempt, as_of ),
        "fix_debt"             : fix_block( fix_debt, prev.get( "fix_debt" ), attempt, as_of ),
        "recent"               : recent[ -MAX_RECENT: ],
    }


def write_summary( path, job, attempt, scan_debt=None, fix_debt=None, work_found_last_run=None, now=None, target=None, err=None ):
    """
    Write the summary of a run.

    Call it from a finally block at the end of every run, whatever the outcome.

    Requires:
        - path is where the registry says this job's summary lives
        - attempt passes check_attempt
    Ensures:
        - returns the record that was written
        - returns None, and says why on err, when the file could not be written: a write failure never fails the job (rule 8)
        - the reader then sees an old written_at and calls the job silent
    Raises:
        - ValueError when the attempt itself is malformed: that is a bug in the caller, not a write failure
    """
    check_attempt( attempt )
    try:
        doc = build_summary( job, attempt, scan_debt, fix_debt, read_summary( path ), work_found_last_run, now, target )
        write_json_atomic( path, doc, indent=2, trailing_newline=True )
        return doc
    except OSError as error:
        print( f"job-summary: could not write {path}: {error}", file=sys.stderr if err is None else err )
        return None


def append_run( runs_path, attempt, extra=None ):
    """
    Append one line for a run to the job's own runs.jsonl.

    The line has the shape of the duplicate check's ledger.

    Requires:
        - attempt passes check_attempt
    Ensures:
        - returns True when the line was appended, False when the file could not be written (never raises for I/O)
    """
    line = { "schema_version": 1, **check_attempt( attempt ), **( extra or {} ) }
    from lupin_mcp.duplicate_check_history import append_line
    try:
        path = pathlib.Path( runs_path )
        append_line( path.parent, line, path.name )
        return True
    except OSError:
        return False
