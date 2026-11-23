#!/usr/bin/env python3
"""
Job alert watcher: tells Rick when a background job goes bad, inside the :8001 arbiter.

Each poll reads the same job summary the jobs accordion shows. A job (or one target of a job) that is
failing, silent or behind gets one alert. While it stays bad it is alerted again at most once per its own
notification interval. A job that turns healthy is forgotten, so its next bad spell alerts at once.

The interval comes from the summary, and the summary applies the run-time overrides file on every read.
Changing a job's interval therefore needs no code change and no restart.

The watcher lives in the arbiter so that a bounce of the dev server on :7999 cannot silence it.
It imports only the standard library at module level. The live summary reader imports the job service
lazily, and that service needs nothing outside the standard library and the Lupin tree.

All decisions are pure and work through injected seams: the summary reader, the notify sender, the state
store, the clock and the logger. Unit tests drive them with a fake clock and need no server.
"""
import datetime
import os
import threading
from typing import Any, Callable, Dict, List, Tuple

from cosa.agents.heartbeat_arbiter.arbiter_journal import DELIVERED_OUTCOMES
from cosa.agents.heartbeat_arbiter.operator_gate_routing import digest_due
from cosa.utils.atomic_json import load_json_dict, write_json_atomic
from cosa.utils.stoppable_daemon import StoppableDaemonMixin
from lupin_arbiter_app.poll_loop import run_poll_loop
from lupin_arbiter_app.health_watcher import SystemClock

BAD_STATES    = ( "failing", "silent", "behind" )
STATE_FILE    = "io/jobs/alert-state.json"
ROW_STATE_FILE   = "io/jobs/job-row-state.json"
ROW_KEY_PREFIX   = "job-health:"
ROW_PROJECT      = "lupin"
ROW_PRIORITY     = "P5"                                   # the floor a cron caller may file at (Rick, 23 Nov 2026); the row's owner raises it
ROW_STATES       = ( "failing", "silent" )                # behind is alerted but never filed: it is not a failure to run
FAILURE_ALERT_SECONDS = 3600                              # a row failure repeats its urgent notice at most this often
UNCONFIRMED      = "the owner is the registry's default and Rick has not confirmed it yet"
MAX_MESSAGE   = 300
DELIVERED     = frozenset( DELIVERED_OUTCOMES | { "posted" } )                 # the live channel's delivered outcomes, and the durable post


def flatten( jobs: List[ dict ] ) -> List[ dict ]:
    """
    List the entries that carry their own state: each target of a job, else the job itself.

    Requires:
        - jobs is the list from the jobs summary; each entry has a targets list, empty when it has none

    Ensures:
        - a job with targets contributes its targets only, so one bad target is one alert, not two
    """
    out = [ ]
    for job in jobs:
        out.extend( job[ "targets" ] if job[ "targets" ] else [ job ] )
    return out


def alert_key( entry: dict ) -> str:
    """
    Name the thing being alerted on.

    Ensures:
        - returns the job id, with a slash and the target when the entry is one target of a job
    """
    return entry[ "job" ] if entry[ "target" ] is None else f"{entry[ 'job' ]}/{entry[ 'target' ]}"


def alert_message( entry: dict ) -> str:
    """
    Write the alert text for one bad entry.

    Ensures:
        - names the job, its target when it has one, its state and its first reason
        - is at most MAX_MESSAGE characters, cut with an ellipsis
    """
    name   = entry[ "title" ] if entry[ "target" ] is None else f"{entry[ 'title' ]} ({entry[ 'target' ]})"
    reason = entry[ "reasons" ][ 0 ][ "text" ] if entry[ "reasons" ] else "no reason recorded"
    text   = f"Background job {name} is {entry[ 'state' ].upper()}: {reason}"
    return text if len( text ) <= MAX_MESSAGE else text[ : MAX_MESSAGE - 1 ] + "…"


def due_alerts( jobs: List[ dict ], state: Dict[ str, str ], now: datetime.datetime ) -> Tuple[ List[ Tuple[ str, str ] ], Dict[ str, str ] ]:
    """
    Pick the alerts due now and work out the state to keep if every one is delivered.

    Requires:
        - jobs is the list from the jobs summary; state maps alert keys to the ISO time of the last alert; now is aware

    Ensures:
        - returns ( alerts, new_state ), where alerts is a list of ( key, message )
        - only failing, silent and behind entries are alerted: unknown and healthy never are
        - an entry with no stored time, or whose interval has passed, gets one message and the stored time becomes now
        - an entry alerted less than its interval ago keeps its stored time and gets no message
        - new_state holds only the keys that are bad now, so a recovered job starts fresh
    """
    messages  = [ ]
    new_state = { }
    for entry in flatten( jobs ):
        if entry[ "state" ] not in BAD_STATES: continue
        key  = alert_key( entry )
        last = state.get( key )
        if digest_due( last, now, entry[ "notify_interval_seconds" ] ):
            messages.append( ( key, alert_message( entry ) ) )
            new_state[ key ] = now.isoformat()
        else:
            new_state[ key ] = last
    return messages, new_state


def decide( jobs: List[ dict ], state: Dict[ str, str ], now: datetime.datetime ) -> Tuple[ List[ str ], Dict[ str, str ] ]:
    """
    Pick the messages due now and the state to keep, assuming each is delivered.

    Ensures:
        - returns ( messages, new_state ) as due_alerts does, with the messages alone and not their keys
    """
    alerts, new_state = due_alerts( jobs, state, now )
    return [ message for _, message in alerts ], new_state


def delivered( outcomes: Any ) -> bool:
    """
    Say whether a send reached anyone.

    Requires:
        - outcomes is what the escalation sink returns: a list of { channel, outcome } dicts

    Ensures:
        - True when at least one channel's outcome is a delivered outcome (the live channel's, or the durable post)
        - False for anything else, including a result that is not a list
    """
    return isinstance( outcomes, list ) and any( isinstance( o, dict ) and o.get( "outcome" ) in DELIVERED for o in outcomes )


def reasons_text( entry: dict ) -> str:
    """Ensures: returns the entry's failing and silent reasons, joined by spaces."""
    return " ".join( r[ "text" ] for r in entry[ "reasons" ] if r[ "state" ] in ROW_STATES )


def row_fingerprint( entry: dict ) -> str:
    """
    Name what a job's row has already been told.

    Ensures:
        - returns a string of the state, the reasons and the last attempt's start
        - the same fault seen again gives the same string, so the row is not amended twice for it
    """
    attempt = entry[ "last_attempt" ][ "started_at" ] if entry[ "last_attempt" ] else "never"
    return f"{entry[ 'state' ]}|{reasons_text( entry )}|{attempt}"


def compose_job_row( entry: dict, owner: str, confirmed: bool ) -> dict:
    """
    Build the row for one failing or silent job.

    Requires:
        - entry is a job entry of the jobs summary in a state of ROW_STATES; owner is the registry's owner key

    Ensures:
        - returns { title, body, owner, accountable, project, correlation_key, priority } for the store's create
        - the key is job-health:<job>, and owner and accountable are the registry owner
        - the body gives the reasons, says when the owner is unconfirmed, and says the row closes by itself
    """
    line = f"Owner: {owner}" + ( " (confirmed)." if confirmed else f" ({UNCONFIRMED})." )
    body = ( f"Why this row exists: the job alert watcher found {entry[ 'title' ]} ({entry[ 'job' ]}) {entry[ 'state' ]}.\n{reasons_text( entry )}\n{line}\n"
             f"What to do: open the Background Jobs page, find the cause and fix it. This row closes by itself when the job is healthy again.\n"
             f"Correlation: one row per job, key {ROW_KEY_PREFIX}{entry[ 'job' ]}; a job that stays red updates this row.\n"
             f"Filed at {ROW_PRIORITY}, the floor for a cron caller. The owner raises it if the job matters now." )
    return { "title": f"[LUPIN] Job health: {entry[ 'title' ]} is {entry[ 'state' ]}", "body": body, "owner": owner, "accountable": owner, "project": ROW_PROJECT,
             "correlation_key": f"{ROW_KEY_PREFIX}{entry[ 'job' ]}", "priority": ROW_PRIORITY }


def sync_job_rows( jobs: List[ dict ], owners: Dict[ str, Tuple[ str, bool ] ], store: Any, state: Dict[ str, str ], now: datetime.datetime ) -> dict:
    """
    Bring the store's job-health rows in line with the jobs summary.

    Requires:
        - jobs is the list from the jobs summary, one entry for each job (a job with targets carries its worst state)
        - owners maps a job id to ( owner key, confirmed )
        - store has find_open( key ), create( **row ), amend( id, note, reason ) and drop( id, reason )
        - state maps a job id to the fingerprint its row was last told

    Ensures:
        - returns { opened, updated, closed, errors, state } as lists of job ids, failure lines and the fingerprints to keep
        - a failing or silent job has exactly one open row: one opened when there is none, and one amended only when the fingerprint changed
        - a healthy job's open row is dropped with a reason naming the time
        - behind and unknown jobs are left as they are
        - one job's failure is listed in errors and never stops the others, and its fingerprint is not recorded
    """
    out, keep = { "opened": [], "updated": [], "closed": [], "errors": [] }, dict( state )
    for entry in jobs:
        job, key = entry[ "job" ], f"{ROW_KEY_PREFIX}{entry[ 'job' ]}"
        if entry[ "state" ] not in ROW_STATES + ( "healthy", ): continue
        try:
            found = store.find_open( key )
            if entry[ "state" ] == "healthy":
                if found:
                    store.drop( found, f"The job is healthy again as of {now.isoformat( timespec='minutes' )}; the job alert watcher closes the row." )
                    out[ "closed" ].append( job )
                keep.pop( job, None )
                continue
            seen = row_fingerprint( entry )
            if found is None:
                owner, confirmed = owners[ job ]
                store.create( **compose_job_row( entry, owner, confirmed ) )
                out[ "opened" ].append( job )
            elif keep.get( job ) != seen:
                store.amend( found, f"Still {entry[ 'state' ]}. {reasons_text( entry )}", "job health row: the job is still red" )
                out[ "updated" ].append( job )
            keep[ job ] = seen
        except Exception as error:                                    # a store, registry or summary fault is named, never swallowed
            out[ "errors" ].append( f"{key}: {type( error ).__name__}: {error}" )
    return { **out, "state": keep }


def make_row_sync( store: Any, owners_fn: Callable[ [], Dict[ str, Tuple[ str, bool ] ] ], state_path: str, log_fn: Callable,
                   read_state_fn: Callable = load_json_dict, write_state_fn: Callable = write_json_atomic ) -> Callable[ [ List[ dict ], datetime.datetime ], List[ str ] ]:
    """
    Build the function the poll calls to keep the job-health rows.

    Requires:
        - owners_fn returns { job id: ( owner key, confirmed ) } and may raise
        - store is as sync_job_rows needs

    Ensures:
        - the returned function takes ( jobs, now ) and returns the list of failure lines, empty when all went well
        - it never raises: an unreadable registry is one failure line
        - the fingerprint file is written only when it changed, and one job_rows event is logged when anything was opened, updated or closed
    """
    def sync( jobs: List[ dict ], now: datetime.datetime ) -> List[ str ]:
        try:
            owners = owners_fn()
        except Exception as error:
            return [ f"job registry unreadable: {type( error ).__name__}: {error}" ]
        state = read_state_fn( state_path )
        out   = sync_job_rows( jobs, owners, store, state, now )
        if out[ "state" ] != state: write_state_fn( state_path, out[ "state" ] )
        if out[ "opened" ] or out[ "updated" ] or out[ "closed" ]: log_fn( "job_rows", opened=out[ "opened" ], updated=out[ "updated" ], closed=out[ "closed" ] )
        return out[ "errors" ]
    return sync


def registry_owners( root: str ) -> Dict[ str, Tuple[ str, bool ] ]:
    """
    Read each job's owner from the job registry.

    Ensures:
        - returns { job id: ( owner as the store's persona key, owner_confirmed is True ) }, "mr-radio" becoming "mr radio"
        - raises what the registry loader raises when the registry is unreadable or invalid
    """
    import cosa.rest.job_registry as jr                           # lazy, like the job service
    from lupin_mcp.persona_normalization import canonical_persona_key
    return { j[ "job" ]: ( canonical_persona_key( j[ "owner" ] ), j.get( "owner_confirmed" ) is True ) for j in jr.load_registry( root )[ "jobs" ] }


def make_live_summary_fn( root: str ) -> Callable[ [], List[ dict ] ]:
    """
    Build the reader of the real job summary.

    Requires:
        - root is the Lupin root that holds src/conf/job-registry.json

    Ensures:
        - the returned function builds the same list GET /api/jobs/summary answers with, in this process
        - the job service is imported on the first call, so a disabled watcher imports nothing
        - the function raises when the registry is unreadable; the poll loop logs that and goes on
    """
    def summary() -> List[ dict ]:
        import cosa.rest.job_service as svc                     # lazy: see the module note
        from cosa.repo.symindex.paths import data_dir
        data = os.environ.get( "LUPIN_REUSE_REVIEW_DATA_ROOT" ) or data_dir( root )
        return svc.build_response( root, data, datetime.datetime.now().astimezone(), svc.LiveDeps( root, data ) )[ "jobs" ]
    return summary


class JobAlertLoop( StoppableDaemonMixin ):
    """The poll loop: read the summary, alert what is due, keep the state."""

    THREAD_NAME = "job-alert-watcher"

    def __init__(
        self,
        summary_fn       : Callable[ [], List[ dict ] ],
        notify_fn        : Callable[ [ str ], Any ],
        state_path       : str,
        log_fn           : Callable,
        interval_seconds : int = 300,
        clock            : Any = None,
        read_state_fn    : Callable = load_json_dict,
        write_state_fn   : Callable = write_json_atomic,
        row_sync_fn      : Any = None,
    ):
        """
        Hold the seams.

        Requires:
            - summary_fn returns the jobs list; notify_fn( message ) returns the sink's list of outcome dicts
            - interval_seconds is a positive int; clock has now() and sleep( seconds )
            - row_sync_fn is None, or make_row_sync's function: ( jobs, now ) returning a list of failure lines
        """
        self.summary_fn       = summary_fn
        self.notify_fn        = notify_fn
        self.state_path       = state_path
        self.log_fn           = log_fn
        self.interval_seconds = interval_seconds
        self.clock            = clock if clock is not None else SystemClock()
        self.read_state_fn    = read_state_fn
        self.write_state_fn   = write_state_fn
        self.row_sync_fn      = row_sync_fn
        self._failure_alerted = None
        self._stop_event      = threading.Event()
        self._thread          = None

    def poll_once( self ) -> int:
        """
        Run one poll.

        Ensures:
            - sends each due alert, then saves the state; the state is saved only after the sends, so a crash re-alerts and never loses one
            - an alert that reached no channel is logged as job_alert_undelivered and its key keeps its old state, so the next poll tries it again
            - logs one job_alert event per message sent
            - returns the number of alerts delivered
            - raises what summary_fn or notify_fn raises, before anything is saved
        """
        state                 = self.read_state_fn( self.state_path )
        jobs, now             = self.summary_fn(), self.clock.now()
        alerts, new_state     = due_alerts( jobs, state, now )
        sent                  = 0
        for key, message in alerts:
            self.log_fn( "job_alert", message=message )
            if delivered( self.notify_fn( message ) ):
                sent += 1
                continue
            self.log_fn( "job_alert_undelivered", message=message )
            if key in state: new_state[ key ] = state[ key ]
            else: del new_state[ key ]
        if new_state != state: self.write_state_fn( self.state_path, new_state )
        if self.row_sync_fn is not None: self._sync_rows( jobs, now )
        return sent

    def _sync_rows( self, jobs: List[ dict ], now: datetime.datetime ) -> None:
        """
        Keep the job-health rows, and say so loudly when one cannot be kept.

        Ensures:
            - a failure is logged as job_row_failed and sent through notify_fn as an urgent alert, at most once per FAILURE_ALERT_SECONDS after one was delivered; an undelivered alert is sent again at the next poll
        """
        errors = self.row_sync_fn( jobs, now )
        if not errors: return
        self.log_fn( "job_row_failed", errors=errors )
        if digest_due( self._failure_alerted, now, FAILURE_ALERT_SECONDS ):
            if delivered( self.notify_fn( f"Job rows could not be kept in step: {len( errors )} failure(s). {errors[ 0 ]}"[ :MAX_MESSAGE ] ) ): self._failure_alerted = now.isoformat()

    def _enabled( self ) -> bool:
        """Ensures: returns True; the arbiter builds this loop only when the watcher is on."""
        return True

    def _loop( self ) -> None:
        """Ensures: polls and sleeps until stop() sets the stop event; a raising poll is logged."""
        run_poll_loop( self._stop_event, self.poll_once, self.log_fn, self.clock, self.interval_seconds )
