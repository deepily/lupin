"""
One-time backfill of job-summary.json from the records the jobs already leave.

It starts no job and edits no row. Each source is read and turned into one or two attempts.
The attempts are written through the shared writer, so the file has the same shape a job's own run would leave. A job that already has a summary is skipped unless --force is given.
Times come from the records themselves; a log with no time inside it is dated by the file's last write, and the evidence says so.
"""
import argparse
import datetime
import json
import os
import pathlib
import re
import sys

import cosa.rest.job_registry as jr
from lupin_mcp import job_summary as js


def aware( naive ):
    """Ensures: returns an aware datetime; a naive time is taken as the host's local time."""
    return naive.astimezone()


def is_file( path ):
    """
    Say whether a regular file can be read.

    Ensures:
        - returns False for a missing file, or one in a folder this process may not enter
    """
    try:
        return pathlib.Path( path ).is_file()
    except OSError:
        return False


def mtime_of( path ):
    """Ensures: returns the aware time the file was last written."""
    return aware( datetime.datetime.fromtimestamp( pathlib.Path( path ).stat().st_mtime ) )


def attempt( when, outcome, evidence, failure=None, stage=None ):
    """
    Build a backfilled attempt.

    Ensures:
        - the attempt started and finished at when and names its source as evidence
        - the trigger is cron, the only value the schedules support, and the evidence says the trigger was not recorded
    """
    return { "started_at": js.iso_now( when ), "finished_at": js.iso_now( when ), "trigger": "cron", "outcome": outcome, "stage": stage, "failure": failure,
             "evidence": f"{evidence}; trigger not recorded", "mode": None }


def step( att, scan=None, fix=None, work=None ):
    """Ensures: returns one replay step."""
    return { "attempt": att, "scan": scan, "fix": fix, "work": work }


def last_json_line( path ):
    """Ensures: returns the last line of the file that parses as a JSON object, or None."""
    for line in reversed( pathlib.Path( path ).read_text( errors="replace" ).splitlines() ):
        line = line.strip()
        if line.startswith( "{" ):
            try: return json.loads( line )
            except ValueError: continue
    return None


def librarian_steps( data ):
    """
    Read the wiki librarian's records.

    Ensures:
        - returns None when there is no log
        - a last good tick from tick-state.json (dated by its last_run_date, midnight local) comes first when the log's last tick failed
        - then the log's last tick, dated by the log's last write
    """
    log, state = data / "librarian" / "librarian.log", data / "librarian" / "tick-state.json"
    last = last_json_line( log ) if is_file( log ) else None
    if last is None: return None
    steps = []
    good  = json.loads( state.read_text() ) if is_file( state ) else None
    def good_step( doc, when, source ):
        return step( attempt( when, "clean", source ), { "unit": "findings", "count": doc.get( "findings" ), "drained_last_run": doc.get( "cleared" ) },
                     { "unit": "rows", "unfiled": doc.get( "deferred" ), "opened_in_run": doc.get( "created" ) }, doc.get( "findings" ) )
    when = mtime_of( log )
    if last.get( "ran" ):
        steps.append( good_step( last, when, f"{log.name} (dated by the file's last write)" ) )
    else:
        if good is not None and good.get( "last_run_date" ):
            steps.append( good_step( good, aware( datetime.datetime.fromisoformat( good[ "last_run_date" ] ) ), "tick-state.json last_run_date (midnight)" ) )
        reason = last.get( "reason" )
        kind   = "skipped" if reason in ( "not due", "switched off" ) else "failed"
        steps.append( step( attempt( when, kind, f"{log.name} (dated by the file's last write)", reason, None if kind == "skipped" else "tick" ) ) )
    return steps


def refresh_steps( data ):
    """
    Read the vector refresh's state file.

    Ensures:
        - returns None when there is no state file
        - a failed last run is preceded by the good build it did not replace, dated by built_at
        - freshness carries built_at and the 36 hour limit; the age is left to the reader
    """
    path = data / "refresh" / "refresh-state.json"
    if not is_file( path ): return None
    doc   = json.loads( path.read_text() )
    scan  = lambda: { "unit": "hours", "count": None, "freshness": { "built_at": doc.get( "built_at" ), "stale_after_hours": 36 } }
    when  = aware( datetime.datetime.fromisoformat( doc[ "last_attempt_at" ] ) ) if doc.get( "last_attempt_at" ) else mtime_of( path )
    steps = []
    if doc.get( "last_outcome" ) == "failed":
        if doc.get( "built_at" ): steps.append( step( attempt( datetime.datetime.fromisoformat( doc[ "built_at" ] ), "clean", "refresh-state.json built_at" ), scan(), None, doc.get( "rows" ) ) )
        steps.append( step( attempt( when, "failed", "refresh-state.json last_attempt_at", doc.get( "last_error" ), "refresh" ) ) )
    else:
        steps.append( step( attempt( when, "clean", "refresh-state.json last_attempt_at" ), scan(), None, doc.get( "rows" ) ) )
    return steps


def behaviour_steps( data ):
    """
    Read the reuse-behaviour log, which has no times and no counts.

    Ensures:
        - returns None when there is no log, or no refusal, skip or page line in it
        - the last such line decides: a refusal is failed, with the line as the failure; a skip is skipped; a page is clean
        - dated by the file's last write
    """
    log = data / "behaviour" / "weekly.log"
    if not is_file( log ): return None
    marks = [ l.strip() for l in log.read_text( errors="replace" ).splitlines() if l.startswith( ( "REFUSING", "SKIPPED", "Reuse behaviour," ) ) ]
    if not marks: return None
    last, when, src = marks[ -1 ], mtime_of( log ), "weekly.log (dated by the file's last write)"
    if last.startswith( "REFUSING" ): return [ step( attempt( when, "failed", src, last[ :200 ], "page" ) ) ]
    return [ step( attempt( when, "skipped" if last.startswith( "SKIPPED" ) else "clean", src ) ) ]


def shadow_steps( data ):
    """
    Read the shadow audit's last JSON line.

    Ensures:
        - returns None when there is no log or no JSON line
        - failed when the line counts failed audits, else clean; dated by the file's last write
    """
    log = data / "shadow-audit" / "shadow-audit.log"
    last = last_json_line( log ) if is_file( log ) else None
    if last is None: return None
    src  = "shadow-audit.log (dated by the file's last write)"
    scan = { "unit": "lookups", "count": None, "drained_last_run": last.get( "audited" ) }
    if last.get( "failed" ): return [ step( attempt( mtime_of( log ), "failed", src, f"{last[ 'failed' ]} audits failed", "audit" ) ) ]
    return [ step( attempt( mtime_of( log ), "clean", src ), scan, None, last.get( "audited" ) ) ]


def sweep_steps( log ):
    """
    Read a sweep log: before, eligible, after, reclaimed.

    Ensures:
        - returns None when there is no log or no eligible line
        - scan debt is what was eligible and not reclaimed; drained is what was reclaimed; dated by the file's last write
    """
    if not is_file( log ): return None
    text = log.read_text( errors="replace" )
    eligible, reclaimed = re.findall( r"eligible\s*:\s*([\d,]+)", text ), re.findall( r"reclaimed\s*:\s*([\d,]+)", text )
    if not eligible: return None
    e, r = int( eligible[ -1 ].replace( ",", "" ) ), int( reclaimed[ -1 ].replace( ",", "" ) ) if reclaimed else 0
    return [ step( attempt( mtime_of( log ), "clean", f"{log.name} (dated by the file's last write)" ), { "unit": "files", "count": max( e - r, 0 ), "drained_last_run": r }, None, e ) ]


def report_steps( log ):
    """
    Read a report log.

    Ensures:
        - returns one step dated by the log's last write: failed when the log shows a traceback, an error word or a non-2xx notify, else clean
        - returns None for a missing or empty log, because an empty log's time is not a run time
    """
    if not is_file( log ) or log.stat().st_size == 0: return None
    text = log.read_text( errors="replace" )
    bad  = re.search( r"Traceback|notify: HTTP (?!2)\d+|\berror\b", text, re.IGNORECASE )
    src  = f"{log.name} (dated by the file's last write)"
    if bad: return [ step( attempt( mtime_of( log ), "failed", src, f"the log mentions: {bad.group( 0 )}", "report" ) ) ]
    return [ step( attempt( mtime_of( log ), "clean", src ) ) ]


def sources( root, data, home ):
    """
    Name every backfill source by registry job id.

    Ensures:
        - returns { job id: callable returning replay steps or None }; the duplicate check is not here, it has its own writer
    """
    logs = pathlib.Path( root ) / "io" / "claude_code_hooks" / "logs"
    return { "wiki-librarian": lambda: librarian_steps( data ), "vector-refresh": lambda: refresh_steps( data ), "reuse-behaviour": lambda: behaviour_steps( data ),
             "shadow-audit": lambda: shadow_steps( data ), "io-tmp-sweep": lambda: sweep_steps( logs / "io-tmp-sweep.log" ),
             "hook-log-sweep": lambda: sweep_steps( logs / "disk-hygiene-sweep.log" ), "disk-report": lambda: report_steps( logs / "disk-hygiene-report.log" ),
             "worktree-census": lambda: report_steps( pathlib.Path( home ) / ".lupin" / "logs" / "worktree-hygiene-report.log" ) }


def replay( path, job, steps ):
    """
    Write a job's steps through the shared writer, oldest first.

    Ensures:
        - returns the last record written, or None when the file could not be written
    """
    doc = None
    for s in steps: doc = js.write_summary( path, job, s[ "attempt" ], s[ "scan" ], s[ "fix" ], s[ "work" ] )
    return doc


def backfill( root, data, home, force=False, dry_run=False, now=None, duplicate_writer=None ):
    """
    Backfill every job that has an existing record.

    Requires:
        - root holds the registry; data is the reuse-review data folder; home holds .lupin/logs
    Ensures:
        - returns [ ( job, status, detail ) ] with status written, would-write, skipped (already has a summary), or no-record
        - starts no job and touches no store row; with dry_run nothing is written
        - a source whose record cannot be read is reported as no-record with the reason, and the others still run
        - the duplicate check is written by its own status writer from runs.jsonl, when that folder has a ledger
    """
    registry = jr.load_registry( root )
    paths    = { j[ "job" ]: jr.resolve_path( j[ "summary_path" ], root, data ) for j in registry[ "jobs" ] }
    rows     = []
    todo     = sources( root, data, home )
    todo[ "duplicate-check" ] = None
    for job in sorted( todo ):
        path = paths[ job ]
        if path.exists() and not force:
            rows.append( ( job, "skipped", "already has a summary" ))
            continue
        if job == "duplicate-check":
            from lupin_mcp import duplicate_check_status as st
            folder = path.parent
            if not is_file( folder / "runs.jsonl" ):
                rows.append( ( job, "no-record", "no runs.jsonl" ) )
                continue
            if not dry_run: ( duplicate_writer or st.write_job_summary )( folder, now or datetime.datetime.now().astimezone() )
            rows.append( ( job, "would-write" if dry_run else "written", "from runs.jsonl" ) )
            continue
        try: steps = todo[ job ]()
        except ( OSError, ValueError, KeyError, TypeError, AttributeError ) as error:                                # one bad record must not stop the others
            rows.append( ( job, "no-record", f"unreadable: {type( error ).__name__}: {error}"[ :120 ] ) )
            continue
        if steps is None: rows.append( ( job, "no-record", "no usable record" ) )
        elif dry_run: rows.append( ( job, "would-write", steps[ -1 ][ "attempt" ][ "outcome" ] + " at " + steps[ -1 ][ "attempt" ][ "started_at" ] ) )
        else:
            doc = replay( path, job, steps )
            rows.append( ( job, "written" if doc else "no-record", doc[ "last_attempt" ][ "outcome" ] + " at " + doc[ "last_attempt" ][ "started_at" ] if doc else "could not write" ) )
    return rows


def main( argv=None, environ=None, out=print ):
    """
    Run the backfill from the command line.

    Ensures:
        - prints one line per job and returns 0
        - --dry-run writes nothing; --force overwrites an existing summary
    """
    environ = os.environ if environ is None else environ
    parser  = argparse.ArgumentParser( prog="python -m lupin_mcp.job_backfill", description="Write job-summary.json from the records the jobs already leave." )
    parser.add_argument( "--dry-run", action="store_true" )
    parser.add_argument( "--force", action="store_true" )
    parser.add_argument( "--root" )
    args    = parser.parse_args( argv )
    from cosa.repo.symindex.paths import data_dir
    root    = args.root or environ.get( "LUPIN_ROOT" ) or os.getcwd()
    data    = pathlib.Path( environ.get( "LUPIN_REUSE_REVIEW_DATA_ROOT" ) or data_dir( root ) )
    for job, status, detail in backfill( root, data, environ.get( "HOME", "/root" ), args.force, args.dry_run ): out( f"{job:20} {status:12} {detail}" )
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    sys.exit( main() )
