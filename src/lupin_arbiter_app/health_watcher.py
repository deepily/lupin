#!/usr/bin/env python3
"""
Health watcher — the dev/test health watch (L2 of the :8001 lupin-arbiter-app service).

Out-of-band, per-container Docker health observation. Each poll inspects each
NAMED container's `.State.Health.Status`, tracks status transitions from our OWN
successive observations (NOT Docker's 5-deep Log, which is probe ExitCodes), and
escalates two edges via an injected `notify_fn` — V1 is NOTIFY-ONLY (auto-bounce
remediation is V2):

    • enter-unhealthy : (starting|healthy) -> unhealthy  (once per episode)
    • flapping        : >= flap_threshold status transitions / flap_window  (once per episode)

Plus a self-watch: after K consecutive polls in which EVERY container's inspect
fails, the watcher escalates "health watcher BLIND" — the watcher noticing it has
gone blind is itself a real signal.

THREE `/health`-never-blocks guards (Tiberius redline):
    1. The health watcher runs on its OWN background thread; GET /health never touches docker.
    2. each `docker inspect` is timeout-bounded at the IO seam (< Docker's probe timeout).
    3. per-container AND per-poll try/except — one bad inspect never kills the loop.

Dev-bounce reshape (Tiberius): :7999 is bounced routinely, so a bounce-burst can
read as flapping. Containers on `flap_exclude` are NEVER flap-paged but STILL get
enter-unhealthy alerts (default excludes `lupin-rest-dev`). Known V1 limitation:
non-excluded containers can still false-flap on a legitimate restart burst;
per-container flap thresholds are a V2 refinement.

All decision logic is pure + seam-injected (`inspect_fn` / `clock` / `notify_fn`
/ `log_fn`) → 100% unit-testable on synthetic Status sequences, NO live docker.
The real `docker inspect` subprocess and the thread spawn/join are the only
`pragma: no cover` IO boundaries.
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
    """Default wall-clock + sleep seam (a FakeClock is injected in unit tests)."""

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
    PURE: map a `docker inspect … {{json .State.Health}}` (returncode, stdout) to
    the Health dict, or None.

    Extracted from docker_inspect_health so the four parse/error arms are unit
    tested (the SOFT→REQUIRED note: a blanket pragma is a test blind spot — that
    is literally how the clean-env boot bug hid).

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
    Run `docker inspect <container> --format '{{json .State.Health}}'`, bounded,
    and delegate parsing to the pure _parse_inspect_result.

    Ensures:
        - returns the parsed `.State.Health` dict on success — Status may be None
          when the container has no healthcheck (returned as {"Status": None})
        - returns None on ANY inspect FAILURE (timeout, daemon down, missing
          container, non-zero exit, unparseable) — None signals failure to the
          BLIND detector
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


# ── pure per-container tracker ──────────────────────────────────────────────

class ContainerHealthTracker:
    """
    Per-container status-transition + flapping state (PURE — no I/O).

    Tracks the last observed status, a rolling deque of transition timestamps
    (pruned to flap_window_seconds), and edge-triggered episode flags so each
    escalation fires ONCE per episode and re-arms on recovery.
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
        Feed one observed status; return the escalation events to fire now
        (subset of {"enter_unhealthy", "flapping"}).

        Requires:
            - status is a non-empty Docker health status (starting|healthy|unhealthy)
            - now is an aware datetime

        Ensures:
            - the FIRST observation is baseline-only (sets last_status, no transition)
            - a changed status records a transition (pruned to the window)
            - enter-unhealthy fires once on (≠unhealthy)→unhealthy; re-arms on →healthy
            - flapping fires once when transitions-in-window ≥ threshold AND the
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


# ── the loop ────────────────────────────────────────────────────────────────

class HealthWatcherLoop:
    """
    Health watcher: poll each named container's docker health, track + escalate, expose
    state. Background-threaded; degrade-safe per-container + per-poll.
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
    ) -> None:
        """
        Requires:
            - containers is a non-empty list of container names
            - interval_seconds, flap_window_seconds, blind_threshold_polls are positive
            - flap_threshold >= 1

        Ensures:
            - one ContainerHealthTracker per container (flap-excluded if listed)
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

        self._containers            = list( containers )
        self._inspect_fn            = inspect_fn
        self._notify_fn             = notify_fn
        self._clock                 = clock if clock is not None else SystemClock()
        self._log_fn                = log_fn if log_fn is not None else _default_log_fn
        self._store                 = store
        self._interval_seconds      = interval_seconds
        self._blind_threshold_polls = blind_threshold_polls

        exclude = set( flap_exclude or [ ] )
        self._trackers = {
            name: ContainerHealthTracker( flap_window_seconds, flap_threshold, name in exclude )
            for name in self._containers
        }
        self._consecutive_all_fail = 0
        self._blind_escalated      = False
        self._stop                 = threading.Event()
        self._thread               = None

    # ── one poll cycle ──────────────────────────────────────────────────────

    def poll_once( self ) -> bool:
        """
        Run ONE poll: inspect each container, track + escalate, update blind +
        state. Returns True iff at least one inspect succeeded this poll.

        Ensures:
            - a per-container inspect failure is swallowed + logged (the loop
              continues to the next container)
            - never raises
        """
        now    = self._clock.now()
        any_ok = False

        for name in self._containers:
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

    def _update_blind( self, any_ok: bool ) -> None:
        """
        Track consecutive all-container inspect failures; escalate ONCE when the
        watcher has gone blind for ≥ blind_threshold_polls; re-arm on any success.
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
        if event == "blind":
            return ( "Health watcher BLIND: docker inspect failing for ALL watched containers — "
                     "the health watch cannot see (escalating)." )
        return f"Health watcher: {event} for '{container}' (status={status})."

    def _write_state( self, now: datetime.datetime ) -> None:
        """Write the health-watcher view to section 'health_watcher' of the shared local store (if any)."""
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
        self._store.set_section( "health_watcher", {
            "containers" : view,
            "blind"      : self._blind_escalated,
            "updated_at" : now.isoformat(),
        } )

    def _log( self, event: str, **fields: Any ) -> None:
        """Emit a structured log event via the injected log_fn."""
        self._log_fn( event, **fields )

    # ── lifecycle ───────────────────────────────────────────────────────────

    def run( self ) -> None:
        """
        Poll loop until stop(): poll_once → sleep, with a per-POLL guard (one bad
        poll never exits the loop — the observer invariant).
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
