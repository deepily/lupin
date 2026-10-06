#!/usr/bin/env python3
"""
Health watcher: the dev and test container health watch of the :8001 arbiter service.

Out-of-band, per-container Docker health observation. Each poll inspects the
`.State.Health.Status` of every named container. It tracks status transitions from its
own successive observations, not from Docker's 5-deep Log, which holds probe ExitCodes.
It escalates two edges through an injected `notify_fn`. The first version only notifies;
automatic bounce remediation is a later refinement.

    • enter-unhealthy : (starting|healthy) -> unhealthy  (once per episode)
    • flapping        : >= flap_threshold status transitions / flap_window  (once per episode)

It also watches itself. After K consecutive polls in which the inspect of every
container fails, the watcher escalates "health watcher BLIND". A watcher that has gone
blind is a real signal in its own right.

Three guards keep `/health` from ever blocking:
    1. The watcher runs on its own background thread; GET /health never touches docker.
    2. Each `docker inspect` is timeout-bounded at the IO seam, below Docker's probe timeout.
    3. Each container and each poll has its own try/except, so one bad inspect never kills the loop.

The dev server on :7999 is bounced routinely, so a bounce burst can read as flapping.
Containers on `flap_exclude` are never paged for flapping but still get enter-unhealthy
alerts. The default excludes `lupin-rest-dev`. Known limitation: containers that are not
excluded can still false-flap on a legitimate restart burst. Per-container flap
thresholds would fix that later.

All decision logic is pure and works through injected seams (`inspect_fn`, `clock`,
`notify_fn`, `log_fn`). Unit tests drive it with synthetic Status sequences and need no
live docker. The real `docker inspect` subprocess and the thread spawn and join are the
only `pragma: no cover` IO boundaries.
"""
import datetime
import json
import subprocess
import threading
import time
from collections import deque
from typing import Any, Callable, Dict, List, Optional

from cosa.agents.heartbeat_arbiter.arbiter_journal import make_log_fn


# ── seams ───────────────────────────────────────────────────────────────────

class SystemClock:
    """Default wall-clock and sleep seam; unit tests inject a FakeClock instead."""

    def now( self ) -> datetime.datetime:
        """Ensures: returns the current aware UTC datetime."""
        return datetime.datetime.now( datetime.timezone.utc )

    def sleep( self, seconds: float ) -> None:   # pragma: no cover - real sleep boundary
        """Ensures: blocks for `seconds` (the real inter-poll wait)."""
        time.sleep( seconds )


# Item A (2026.06.11 receipts design §2.3): the line shape has ONE owner —
# arbiter_journal.make_log_fn (ts + ts_local). This module-level default keeps
# the historical name; production wiring (assemble_app) builds INI-tz'd,
# per-loop log_fns from the same builder.
_default_log_fn = make_log_fn( loop="health_watcher" )


def _parse_inspect_result( returncode: int, stdout: Optional[ str ] ) -> Optional[ dict ]:
    """
    Pure: map a docker health inspect (returncode, stdout) to the Health dict, or None.

    The command is `docker inspect … {{json .State.Health}}`. It is split out of
    docker_inspect_health so that the four parse and error arms are unit tested. A
    blanket pragma on the whole function would leave them untested.

    Ensures:
        - returncode != 0 → None (inspect failed / no such container)
        - empty or "null" stdout → {"Status": None} (inspect OK, no healthcheck)
        - valid JSON → the parsed dict
        - unparseable JSON → None
    """
    if returncode != 0:
        return None
    raw = ( stdout or "" ).strip()
    if not raw or raw == "null":
        return { "Status": None }                    # inspect OK, no healthcheck
    try:
        return json.loads( raw )
    except json.JSONDecodeError:
        return None


def docker_inspect_health( container: str, timeout_seconds: float ) -> Optional[ dict ]:   # pragma: no cover - real subprocess IO boundary
    """
    Run a bounded `docker inspect` for `.State.Health` and parse the result.

    Parsing is delegated to _parse_inspect_result. The command is
    `docker inspect <container> --format '{{json .State.Health}}'`.

    Ensures:
        - returns the parsed `.State.Health` dict on success; Status may be None
          when the container has no healthcheck (returned as {"Status": None})
        - returns None on any inspect failure (timeout, daemon down, missing
          container, non-zero exit, unparseable); None signals the failure to the
          blind detector
        - never raises (every failure mode maps to None)
    """
    try:
        proc = subprocess.run(
            [ "docker", "inspect", container, "--format", "{{json .State.Health}}" ],
            capture_output = True, text = True, timeout = timeout_seconds,
        )
    except ( subprocess.TimeoutExpired, subprocess.SubprocessError, OSError ):
        return None
    return _parse_inspect_result( proc.returncode, proc.stdout )


# ── crash-loop signal: docker .State.RestartCount ────────────────────────────

def _parse_restart_count( returncode: int, stdout: Optional[ str ] ) -> Optional[ int ]:
    """
    Pure: map a docker RestartCount inspect (returncode, stdout) to an int, or None.

    The command is `docker inspect … {{.RestartCount}}`. Any failure gives None.
    RestartCount moves only when the restart policy auto-restarts a crashed container.
    A manual `docker restart` leaves it unchanged, so crash-loop detection keys on it.

    Ensures:
        - returncode != 0 → None (inspect failed / no such container)
        - empty stdout → None (the field always prints for a real container)
        - a parseable integer → that int
        - anything non-integer → None
    """
    if returncode != 0:
        return None
    raw = ( stdout or "" ).strip()
    if not raw:
        return None
    try:
        return int( raw )
    except ValueError:
        return None


def docker_inspect_restart_count( container: str, timeout_seconds: float ) -> Optional[ int ]:   # pragma: no cover - real subprocess IO boundary
    """
    Run a bounded `docker inspect` for RestartCount, then parse it with _parse_restart_count.

    The command is `docker inspect <container> --format '{{.RestartCount}}'`.

    Ensures:
        - returns the integer .State.RestartCount on success
        - returns None on any inspect failure (timeout, daemon down, missing
          container, non-zero exit, unparseable)
        - never raises (every failure mode maps to None)
    """
    try:
        proc = subprocess.run(
            [ "docker", "inspect", container, "--format", "{{.RestartCount}}" ],
            capture_output = True, text = True, timeout = timeout_seconds,
        )
    except ( subprocess.TimeoutExpired, subprocess.SubprocessError, OSError ):
        return None
    return _parse_restart_count( proc.returncode, proc.stdout )


# ── reload-blindness signal: docker .Config.Env ──────────────────────────────

def _parse_env_value( env_list: Optional[ list ], key: str ) -> Optional[ str ]:
    """
    Pure: extract one key's value from a docker `.Config.Env` list of "K=V" strings.

    Ensures:
        - None or empty env_list → None
        - the last "KEY=…" occurrence wins (docker's own precedence)
        - a matching entry with an empty value → "" (not None)
        - no match → None
    """
    if not env_list:
        return None
    value = None
    for entry in env_list:
        if isinstance( entry, str ) and entry.startswith( key + "=" ):
            value = entry[ len( key ) + 1: ]
    return value


def docker_inspect_env( container: str, timeout_seconds: float ) -> Optional[ list ]:   # pragma: no cover - real subprocess IO boundary
    """
    Run a bounded `docker inspect` for `.Config.Env`; return the env list, or None on failure.

    The command is `docker inspect <container> --format '{{json .Config.Env}}'`.
    It never raises.
    """
    try:
        proc = subprocess.run(
            [ "docker", "inspect", container, "--format", "{{json .Config.Env}}" ],
            capture_output = True, text = True, timeout = timeout_seconds,
        )
    except ( subprocess.TimeoutExpired, subprocess.SubprocessError, OSError ):
        return None
    if proc.returncode != 0:
        return None
    raw = ( proc.stdout or "" ).strip()
    if not raw or raw == "null":
        return None
    try:
        return json.loads( raw )
    except json.JSONDecodeError:
        return None


def assess_reload_blindness( container: str, env_inspect_fn: Callable[ [ str ], Optional[ list ] ],
                             *, reload_decider: Callable[ [ Optional[ str ], bool ], bool ] ):
    """
    Decide whether crash-loop detection is blind to worker-only crashes on `container`.

    It is blind when uvicorn --reload is armed there. The reloader, not the worker, is
    then the container's main process, and it respawns a crashed worker while the
    container stays up. RestartCount never moves, so the state is announced loudly.

    Requires:
        - env_inspect_fn( container ) → the docker `.Config.Env` list (or None)
        - reload_decider( env_value, is_prod_or_test ) → bool; this is the shared
          gate lupin_app.bootstrap_helpers.reload_enabled, reused so this check
          cannot drift from the reload decision in main.py

    Ensures:
        - env inspect None / raising → ( "unknown", None ) — no false all-clear
        - reload armed → ( "blind", <loud warning message> )
        - reload off → ( "ok", None )
        - is_prod_or_test is true when LUPIN_ENV (trimmed, lowercased) is production,
          test or testing, the same set main.py uses
        - never raises
    """
    try:
        env_list = env_inspect_fn( container )
    except Exception:
        env_list = None
    if env_list is None:
        return ( "unknown", None )
    reload_value = _parse_env_value( env_list, "LUPIN_RELOAD" )
    lupin_env    = ( _parse_env_value( env_list, "LUPIN_ENV" ) or "" ).strip().lower()
    is_prod_or_test = lupin_env in ( "production", "test", "testing" )
    if reload_decider( reload_value, is_prod_or_test ):
        msg = ( f"Health watcher: crash-loop detection is BLIND to worker-only crashes on "
                f"'{container}' — uvicorn --reload is ARMED (LUPIN_RELOAD set), so a crashing "
                f"worker is respawned WITHOUT the container exiting and RestartCount never moves. "
                f"Turn reload off to restore crash-loop paging on '{container}'." )
        return ( "blind", msg )
    return ( "ok", None )


# ── pure per-container tracker ──────────────────────────────────────────────

class ContainerHealthTracker:
    """
    Per-container status-transition and flapping state (pure, no I/O).

    Tracks the last observed status, a rolling deque of transition timestamps
    (pruned to flap_window_seconds), and edge-triggered episode flags. Each
    escalation fires once per episode and re-arms on recovery.
    """

    def __init__( self, flap_window_seconds: int, flap_threshold: int, flap_excluded: bool ) -> None:
        self.flap_window_seconds  = flap_window_seconds
        self.flap_threshold       = flap_threshold
        self.flap_excluded        = flap_excluded
        self.last_status          = None
        self.transitions          = deque()
        self._unhealthy_escalated = False
        self._flap_escalated      = False

    def observe( self, status: str, now: datetime.datetime ) -> List[ str ]:
        """
        Feed one observed status and return the events to fire now.

        The events are a subset of {"enter_unhealthy", "flapping"}.

        Requires:
            - status is a non-empty Docker health status (starting|healthy|unhealthy)
            - now is an aware datetime

        Ensures:
            - the first observation is baseline-only (sets last_status, no transition)
            - a changed status records a transition (pruned to the window)
            - enter-unhealthy fires once on (≠unhealthy)→unhealthy; re-arms on →healthy
            - flapping fires once when transitions-in-window ≥ threshold and the
              container is not flap-excluded; re-arms when the window clears
            - never raises
        """
        events : List[ str ] = [ ]

        # re-arm the enter-unhealthy episode whenever we read healthy
        if status == "healthy":
            self._unhealthy_escalated = False

        if self.last_status is None:
            self.last_status = status                # warm-up baseline — no transition
            return events

        if status != self.last_status:
            self.last_status = status
            self.transitions.append( now )
            self._prune( now )
            if status == "unhealthy" and not self._unhealthy_escalated:
                self._unhealthy_escalated = True
                events.append( "enter_unhealthy" )
            if ( not self.flap_excluded ) and self.is_flapping() and not self._flap_escalated:
                self._flap_escalated = True
                events.append( "flapping" )
        else:
            self._prune( now )

        # re-arm the flapping episode once the window drops below threshold
        if self._flap_escalated and not self.is_flapping():
            self._flap_escalated = False
        return events

    def _prune( self, now: datetime.datetime ) -> None:
        """Drop transition timestamps older than the flap window (rolling)."""
        while self.transitions and ( now - self.transitions[ 0 ] ).total_seconds() > self.flap_window_seconds:
            self.transitions.popleft()

    def is_flapping( self ) -> bool:
        """Ensures: True iff transitions-in-window ≥ flap_threshold."""
        return len( self.transitions ) >= self.flap_threshold

    def transitions_in_window( self ) -> int:
        """Ensures: returns the count of transitions currently in the window."""
        return len( self.transitions )


class RestartLoopTracker:
    """
    Per-container crash-loop detector based on docker RestartCount (pure, no I/O).

    The health and flap path misses a fast crash that restarts before the healthcheck
    registers "unhealthy". ContainerHealthTracker cannot see it. Also, lupin-rest-dev
    is flap-excluded. This tracker keys on the restart policy's RestartCount
    instead. A sanctioned bounce never moves that count. `docker restart` reuses the
    container. `compose up --force-recreate` makes a new container with the count
    reset to 0. So it fires only on unsanctioned policy restarts. It is not gated on
    flap exclusion. A crash-loop must page even for an excluded container.

    The threshold is chosen to tolerate a one-off crash, since a single crash that
    recovers is not a loop. It is not a measured baseline. Default 2: two policy
    restarts inside the window make a loop.

    Fires "crash_loop" once per episode; re-arms when the window clears.
    """

    def __init__( self, window_seconds: int, threshold: int ) -> None:
        self.window_seconds = window_seconds
        self.threshold      = threshold
        self.last_count     = None
        self.rises          = deque()             # timestamps of observed RestartCount increments
        self._escalated     = False

    def observe( self, restart_count: int, now: datetime.datetime ) -> List[ str ]:
        """
        Feed one ( RestartCount, now ) observation and return the events to fire now.

        The events are a subset of {"crash_loop"}.

        Requires:
            - restart_count is a non-negative int (docker .State.RestartCount)
            - now is an aware datetime

        Ensures:
            - the first observation is baseline-only (sets last_count, no rise)
            - an increase records one rise timestamp per unit of increase (pruned
              to the window); crash_loop fires once when rises-in-window ≥ threshold
            - a decrease (a recreate reset to 0, same name, new container id)
              fully resets the episode state (rise deque, flag, baseline); a
              sanctioned recreate is a clean slate, never a negative rise
            - an unchanged count records no rise
            - re-arms (clears the episode flag) when the window drops below threshold
            - never raises
        """
        events : List[ str ] = [ ]
        self._prune( now )

        if self.last_count is None:
            self.last_count = restart_count           # warm-up baseline — no rise
            return events

        if restart_count < self.last_count:
            # a recreate reset the count downward → clean slate, NOT a rise
            self.rises.clear()
            self._escalated = False
            self.last_count = restart_count
            return events

        if restart_count > self.last_count:
            for _ in range( restart_count - self.last_count ):
                self.rises.append( now )
            self._prune( now )
            if len( self.rises ) >= self.threshold and not self._escalated:
                self._escalated = True
                events.append( "crash_loop" )
        self.last_count = restart_count               # equal count records no rise

        if self._escalated and len( self.rises ) < self.threshold:
            self._escalated = False
        return events

    def _prune( self, now: datetime.datetime ) -> None:
        """Drop rise timestamps older than the window (rolling)."""
        while self.rises and ( now - self.rises[ 0 ] ).total_seconds() > self.window_seconds:
            self.rises.popleft()

    def rises_in_window( self ) -> int:
        """Ensures: returns the count of RestartCount rises currently in the window."""
        return len( self.rises )


# ── the loop ────────────────────────────────────────────────────────────────

class HealthWatcherLoop:
    """
    Poll each named container's docker health, track and escalate, and expose state.

    Runs on a background thread. A failure is contained per container and per poll.
    """

    def __init__(
        self,
        containers              : List[ str ],
        inspect_fn              : Callable[ [ str ], Optional[ dict ] ],
        notify_fn               : Callable[ [ str ], None ],
        *,
        clock                   : Optional[ Any ]      = None,
        log_fn                  : Optional[ Callable ] = None,
        store                   : Optional[ Any ]      = None,
        interval_seconds        : int                  = 30,
        flap_window_seconds     : int                  = 600,
        flap_threshold          : int                  = 3,
        flap_exclude            : Optional[ List[ str ] ] = None,
        blind_threshold_polls   : int                  = 3,
        restart_inspect_fn      : Optional[ Callable[ [ str ], Optional[ int ] ] ] = None,
        restart_loop_threshold  : int                  = 2,
    ) -> None:
        """
        Validate the arguments and build one health tracker and one restart tracker per container.

        Requires:
            - containers is a non-empty list of container names
            - interval_seconds, flap_window_seconds, blind_threshold_polls are positive
            - flap_threshold >= 1 and restart_loop_threshold >= 1

        Ensures:
            - one ContainerHealthTracker per container (flap-excluded if listed)
            - one RestartLoopTracker per container (not flap-gated: a crash-loop
              pages even for an excluded container); the crash-loop window reuses
              flap_window_seconds
            - crash-loop detection is active iff restart_inspect_fn is provided
            - injected seams resolved (clock → SystemClock, log_fn → structured JSON)
            - raises ValueError on any invariant violation
        """
        if not containers:
            raise ValueError( "containers must be a non-empty list" )
        if interval_seconds <= 0:
            raise ValueError( f"interval_seconds must be positive, got {interval_seconds}" )
        if flap_window_seconds <= 0:
            raise ValueError( f"flap_window_seconds must be positive, got {flap_window_seconds}" )
        if flap_threshold < 1:
            raise ValueError( f"flap_threshold must be >= 1, got {flap_threshold}" )
        if blind_threshold_polls <= 0:
            raise ValueError( f"blind_threshold_polls must be positive, got {blind_threshold_polls}" )
        if restart_loop_threshold < 1:
            raise ValueError( f"restart_loop_threshold must be >= 1, got {restart_loop_threshold}" )

        self._containers            = list( containers )
        self._inspect_fn            = inspect_fn
        self._notify_fn             = notify_fn
        self._clock                 = clock if clock is not None else SystemClock()
        self._log_fn                = log_fn if log_fn is not None else _default_log_fn
        self._store                 = store
        self._interval_seconds      = interval_seconds
        self._blind_threshold_polls = blind_threshold_polls
        self._restart_inspect_fn    = restart_inspect_fn

        exclude = set( flap_exclude or [ ] )
        self._trackers = {
            name: ContainerHealthTracker( flap_window_seconds, flap_threshold, name in exclude )
            for name in self._containers
        }
        self._restart_trackers = {
            name: RestartLoopTracker( flap_window_seconds, restart_loop_threshold )
            for name in self._containers
        }
        self._consecutive_all_fail = 0
        self._blind_escalated      = False
        self._stop                 = threading.Event()
        self._thread               = None

    # ── one poll cycle ──────────────────────────────────────────────────────

    def poll_once( self ) -> bool:
        """
        Run one poll: inspect each container, track and escalate, update blind and state.

        Returns True iff at least one inspect succeeded this poll.

        Ensures:
            - a per-container inspect failure is swallowed and logged (the loop
              continues to the next container)
            - never raises
        """
        now    = self._clock.now()
        any_ok = False

        for name in self._containers:
            # crash-loop detection runs FIRST + independent of the health continues
            # below (a fast crash never reaches a health status, and dev is
            # flap-excluded) — a crash-loop must page even when health says nothing.
            if self._restart_inspect_fn is not None:
                self._observe_restart_count( name, now )

            try:
                health = self._inspect_fn( name )            # dict on success, None on failure
            except Exception as e:                           # per-container guard
                health = None
                self._log( "inspect_error", container=name, error=str( e ) )

            if health is None:
                self._log( "inspect_failed", container=name )
                continue

            any_ok = True
            status = health.get( "Status" ) or None
            if not status or status == "none":
                self._log( "health_unknown", container=name )
                continue                                     # no healthcheck → skip tracking

            events = self._trackers[ name ].observe( status, now )
            self._log( "health_obs", container=name, status=status,
                       transitions=self._trackers[ name ].transitions_in_window() )
            for ev in events:
                self._escalate( ev, name, status )

        self._update_blind( any_ok )
        self._write_state( now )
        return any_ok

    def _observe_restart_count( self, name: str, now: datetime.datetime ) -> None:
        """
        Inspect docker RestartCount for `name`, feed the crash-loop tracker, and escalate events.

        A restart-inspect failure or raise is logged and skipped. This method never
        raises and never kills the poll. It does not feed the blind detector, which
        concerns health inspects only.
        """
        try:
            count = self._restart_inspect_fn( name )         # int on success, None on failure
        except Exception as e:                               # per-container guard
            count = None
            self._log( "restart_inspect_error", container=name, error=str( e ) )
        if count is None:
            self._log( "restart_inspect_failed", container=name )
            return
        events = self._restart_trackers[ name ].observe( count, now )
        self._log( "restart_obs", container=name, restart_count=count,
                   rises=self._restart_trackers[ name ].rises_in_window() )
        for ev in events:
            self._escalate( ev, name, str( count ) )

    def _update_blind( self, any_ok: bool ) -> None:
        """
        Count consecutive polls where every inspect failed; escalate once at the threshold.

        Escalates once when the watcher has been blind for ≥ blind_threshold_polls
        polls. Any success re-arms it.
        """
        if any_ok:
            self._consecutive_all_fail = 0
            self._blind_escalated      = False
            return
        self._consecutive_all_fail += 1
        if self._consecutive_all_fail >= self._blind_threshold_polls and not self._blind_escalated:
            self._blind_escalated = True
            self._escalate( "blind", None, None )

    def _escalate( self, event: str, container: Optional[ str ], status: Optional[ str ] ) -> None:
        """Fire one escalation via notify_fn (V1 notify-only); swallow notify errors."""
        msg = self._format_escalation( event, container, status )
        self._log( "escalate", escalation=event, container=container )
        try:
            self._notify_fn( msg )
        except Exception as e:                               # notify must never kill the loop
            self._log( "notify_error", escalation=event, error=str( e ) )

    @staticmethod
    def _format_escalation( event: str, container: Optional[ str ], status: Optional[ str ] ) -> str:
        """Build the human-readable escalation message for an event."""
        if event == "enter_unhealthy":
            return f"Health watcher: container '{container}' entered UNHEALTHY (docker health)."
        if event == "flapping":
            return f"Health watcher: container '{container}' is FLAPPING (≥ threshold health transitions in window)."
        if event == "crash_loop":
            return ( f"Health watcher: container '{container}' is CRASH-LOOPING (docker RestartCount rose "
                     f"≥ threshold in window; count={status}). The restart policy is auto-restarting a "
                     f"crashing container — a sanctioned bounce does not move this counter." )
        if event == "blind":
            return ( "Health watcher BLIND: docker inspect failing for ALL watched containers — "
                     "the health watch cannot see (escalating)." )
        return f"Health watcher: {event} for '{container}' (status={status})."

    def _write_state( self, now: datetime.datetime ) -> None:
        """Write the watcher view to the 'health_watcher' section of the local store, if any."""
        if self._store is None:
            return
        view = {
            name: {
                "status"                : tr.last_status,
                "transitions_in_window" : tr.transitions_in_window(),
                "flapping"              : ( not tr.flap_excluded ) and tr.is_flapping(),
                "flap_excluded"         : tr.flap_excluded,
            }
            for name, tr in self._trackers.items()
        }
        restart_view = {
            name: {
                "restart_count"   : tr.last_count,
                "rises_in_window" : tr.rises_in_window(),
            }
            for name, tr in self._restart_trackers.items()
        }
        self._store.set_section( "health_watcher", {
            "containers"    : view,
            "restart_watch" : restart_view,
            "blind"         : self._blind_escalated,
            "updated_at"    : now.isoformat(),
        } )

    def _log( self, event: str, **fields: Any ) -> None:
        """Emit a structured log event via the injected log_fn."""
        self._log_fn( event, **fields )

    # ── lifecycle ───────────────────────────────────────────────────────────

    def run( self ) -> None:
        """
        Poll until stop(): poll_once, then sleep, with a guard around each poll.

        One bad poll never exits the loop, because the observer must keep observing.
        """
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception as e:                           # per-poll guard
                self._log( "poll_error", error=str( e ) )
            self._clock.sleep( self._interval_seconds )

    def start( self ) -> None:
        """Spawn the daemon poll thread."""
        self._thread = threading.Thread( target=self.run, name="health-watcher", daemon=True )
        self._thread.start()

    def stop( self ) -> None:
        """Signal stop and join the poll thread (no-op if never started)."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join( timeout=5 )
