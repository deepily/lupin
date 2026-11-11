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
from typing import Any, Callable, Dict, List, Optional, Tuple

from cosa.agents.heartbeat_arbiter.arbiter_journal import DELIVERED_OUTCOMES
from cosa.utils.atomic_json import load_json_dict, write_json_atomic
from lupin_arbiter_app.poll_loop import run_poll_loop
from lupin_arbiter_app.health_watcher import SystemClock

BAD_STATES    = ( "failing", "silent", "behind" )
STATE_FILE    = "io/jobs/alert-state.json"
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


def _due( last_iso: Optional[ str ], now: datetime.datetime, interval_seconds: int ) -> bool:
    """
    Say whether an alert is due.

    Ensures:
        - True when nothing was alerted before, when the stored time cannot be read, or when the interval has passed
        - False when the last alert was less than the interval ago, or lies in the future (clock skew)
    """
    if last_iso is None: return True
    try:
        last = datetime.datetime.fromisoformat( last_iso )
    except ValueError:
        return True
    return ( now - last ).total_seconds() >= interval_seconds


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
        if _due( last, now, entry[ "notify_interval_seconds" ] ):
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


class JobAlertLoop:
    """The poll loop: read the summary, alert what is due, keep the state."""

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
    ):
        """
        Hold the seams.

        Requires:
            - summary_fn returns the jobs list; notify_fn( message ) returns the sink's list of outcome dicts
            - interval_seconds is a positive int; clock has now() and sleep( seconds )
        """
        self.summary_fn       = summary_fn
        self.notify_fn        = notify_fn
        self.state_path       = state_path
        self.log_fn           = log_fn
        self.interval_seconds = interval_seconds
        self.clock            = clock if clock is not None else SystemClock()
        self.read_state_fn    = read_state_fn
        self.write_state_fn   = write_state_fn
        self._stop            = threading.Event()
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
        alerts, new_state     = due_alerts( self.summary_fn(), state, self.clock.now() )
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
        return sent

    def start( self ) -> None:                                  # pragma: no cover - thread spawn boundary
        """Ensures: the poll loop runs on a daemon thread until stop() is called."""
        self._thread = threading.Thread(
            target = run_poll_loop,
            args   = ( self._stop, self.poll_once, self.log_fn, self.clock, self.interval_seconds ),
            name   = "job-alert-watcher",
            daemon = True,
        )
        self._thread.start()

    def stop( self ) -> None:                                   # pragma: no cover - thread join boundary
        """Ensures: the loop is told to stop and its thread is joined briefly."""
        self._stop.set()
        if self._thread is not None: self._thread.join( timeout=5 )
