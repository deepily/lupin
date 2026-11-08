"""
Adapters that turn a run of three jobs into a job-summary/1 record.

The jobs are the wiki librarian, the vector refresh and the reuse-behaviour page. Each adapter is called once at the end of a run, from the job's own `main`.
It takes the result the job already computed. None of them reads the job's log files.
They take the run's own summary and exit code, so the record cannot disagree with what the job said.
The duplicate check writes its own record. The symbol index is rebuilt by the vector refresh (vector_refresh.run_refresh calls
build.ensure), so the vector-refresh record covers it.
"""
import datetime
import os

from lupin_mcp import host_snapshot as hs
from lupin_mcp import job_summary as js

FILE_NAME         = "job-summary.json"
STALE_AFTER_HOURS = 36                                                # the vector refresh's own limit (reuse-review refresh/vector-status.json)
SKIPPED_REASONS   = ( "not due", "switched off", "BUILD_LOCK_HELD" )  # a run that decided nothing was due is a skipped run, not a failure


def aware( when ):
    """Ensures: returns an aware datetime; a naive time is taken as local."""
    return when.astimezone()


def outcome_of( summary, code, held_code=2 ):
    """
    Say how a run ended, from the summary the job printed and its exit code.

    Requires:
        - summary is the job's run summary with ran and, when ran is false, a reason
    Ensures:
        - returns ( outcome, failure ): skipped for a run that was not due, switched off or refused by a lock; failed for any other run that did not finish
        - a run that finished is clean, or carried when its exit code is held_code (work was held back)
    """
    if summary.get( "ran" ):
        return ( "carried" if code == held_code else "clean" ), None
    if summary.get( "reason" ) in SKIPPED_REASONS: return "skipped", summary.get( "reason" )
    return "failed", summary.get( "reason" )


def report( folder, job, now, outcome, failure=None, stage=None, mode=None, scan=None, fix=None, work=None, environ=None ):
    """
    Write the record of one run into folder/job-summary.json.

    Requires:
        - folder is the job's own data folder; now is the run's start time
    Ensures:
        - returns the record written, or None when the file could not be written (a write failure never fails the job)
        - the trigger is cron unless the environment says hand (Run now sets LUPIN_JOB_TRIGGER)
    """
    attempt = { "started_at": js.iso_now( aware( now ) ), "finished_at": js.iso_now(), "trigger": js.trigger_from_env( "cron", environ ),
                "outcome": outcome, "stage": stage, "failure": failure, "evidence": None, "mode": mode }
    written = js.write_summary( os.path.join( folder, FILE_NAME ), job, attempt, scan, fix, work )
    hs.refresh_best_effort( environ )                                  # the container cannot read the crontab; this host run leaves a copy for it
    return written


def record_librarian( folder, summary, code, now, environ=None ):
    """
    Record one wiki-librarian tick.

    Requires:
        - summary and code are what librarian_tick.run_tick returned
    Ensures:
        - scan debt is the open findings; fix debt is the rows the tick created, with the rows it deferred as unfiled
        - a failed tick carries the old debts forward (the writer keeps them)
    """
    outcome, failure = outcome_of( summary, code )
    scan = { "unit": "findings", "count": summary.get( "findings" ), "drained_last_run": summary.get( "cleared" ) } if summary.get( "ran" ) else None
    fix  = { "unit": "rows", "own_mark": None, "unfiled": summary.get( "deferred" ), "opened_in_run": summary.get( "created" ) } if summary.get( "ran" ) else None
    return report( folder, "wiki-librarian", now, outcome, failure, None if outcome != "failed" else "tick", None, scan, fix, summary.get( "findings" ), environ )


def record_refresh( folder, summary, code, state, now, environ=None ):
    """
    Record one vector-refresh run, which also rebuilds the symbol index.

    Requires:
        - summary and code are what vector_refresh.run_refresh returned; state is the refresh state file as it stands after the run
    Ensures:
        - the debt is staleness: built_at from the run when it built, else from the state file, with the 36 hour limit; the age is computed by the reader
        - a failed run carries the old figures forward
    """
    outcome, failure = outcome_of( summary, code, held_code=None )
    built = summary.get( "built_at" ) or state.get( "built_at" )
    scan  = { "unit": "hours", "count": None, "freshness": { "built_at": built, "stale_after_hours": STALE_AFTER_HOURS } } if summary.get( "ran" ) else None
    return report( folder, "vector-refresh", now, outcome, failure, None if outcome != "failed" else "refresh", None, scan, None, summary.get( "rows" ), environ )


def record_behaviour( folder, outcome, now, failure=None, environ=None ):
    """
    Record one reuse-behaviour run, the job that had no ledger.

    Requires:
        - outcome is clean (page made), skipped (already saved) or failed (refused, with the reason)
    Ensures:
        - the record names no debt: the job builds a page and owes nothing
    """
    return report( folder, "reuse-behaviour", now, outcome, failure, None if outcome != "failed" else "page", None, None, None, None, environ )
