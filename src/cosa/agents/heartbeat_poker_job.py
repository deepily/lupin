"""
HeartbeatPokerJob — generic heartbeat-poker agentic job (CJ Flow Layer 1).

Wakes N recipient sessions on a fixed cadence and exits on a terminating
condition. Use-case-agnostic: the poker never branches on recipient role —
variance lives in per-recipient config + Layer-2 recipient doctrine.

Design doc : src/rnd/v0.1.7/2026.05.20-generic-heartbeat-poker-abstraction-design.md
Class spec : src/rnd/v0.1.7/2026.05.22-heartbeat-poker-d1d4-class-spec.md

TASK SCOPE — this module is tasks I1 + I2:
  I1 — the class shape: __init__ + config validation, the cadence / poke
       loop, recipient routing, poke_body construction, the Clock seam.
  I2 — the three layered exits (clean-signal / dead-man's-switch / hard-cap)
       + notify() integration. The dead-man's-switch ESCALATES, never
       terminates (design doc §4).

I1-followup: the production CommonsGateway implementation (CommonsStore-backed)
is bound separately — see the d1d4 spec §9. The reference pattern (CommonsStore
.post() + a commons push) was the legacy cascade scheduler's `fire_heartbeat()`,
retired 2026-06-29 under the ddaa2882 waiver + design-doc I8. For now `commons` is a required
injected dependency (the agentic-job factory supplies the real gateway in
production; tests supply a fake).

I2-followup: `_iso_is_after()` assumes SystemClock.now_iso() and the gateway's
last_post_ts() are timezone-consistent. Verify both are tz-aware UTC during
integration; the lexical fallback is defensive only.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Dict, List, Optional, Protocol, runtime_checkable

import cosa.utils.util as cu
from cosa.agents.agentic_job_base import AgenticJobBase


# Valid enum values for RecipientSpec — module constants so callers + tests share them.
RECIPIENT_IDENTIFIER_TYPES = ( "persona", "session_id" )
RECIPIENT_ROLES            = ( "manager", "observer", "watcher" )


@dataclass( frozen=True )
class RecipientSpec:
    """
    Per-recipient poker config (design doc §3, finding F-Rio-B1).

    Requires:
        - identifier is a non-empty string
        - identifier_type is one of RECIPIENT_IDENTIFIER_TYPES
        - role is one of RECIPIENT_ROLES

    Ensures:
        - immutable after construction (frozen)
        - an invalid identifier / identifier_type / role raises ValueError

    `role` is opaque passthrough — stamped into poke_body.role; the poker
    never branches on it (design doc §2 structural insight).
    """
    identifier      : str
    identifier_type : str
    role            : str

    def __post_init__( self ) -> None:
        if not self.identifier or not isinstance( self.identifier, str ):
            raise ValueError( f"RecipientSpec.identifier must be a non-empty string, got {self.identifier!r}" )
        if self.identifier_type not in RECIPIENT_IDENTIFIER_TYPES:
            raise ValueError( f"RecipientSpec.identifier_type must be one of {RECIPIENT_IDENTIFIER_TYPES}, got {self.identifier_type!r}" )
        if self.role not in RECIPIENT_ROLES:
            raise ValueError( f"RecipientSpec.role must be one of {RECIPIENT_ROLES}, got {self.role!r}" )


@runtime_checkable
class Clock( Protocol ):
    """
    Injectable time source — the clock-injection seam (finding F-Rio-E7).

    Production = SystemClock. Tests = a FakeClock that advances on command,
    so the cadence / hard-cap loop is exercised without real waiting — the
    prerequisite for I6's 100% branch-coverage target.
    """
    def monotonic( self ) -> float: ...
    def now_iso( self ) -> str: ...
    async def sleep( self, seconds: float ) -> None: ...


class SystemClock:
    """Real Clock — wraps time.monotonic, cu.get_current_datetime_iso, asyncio.sleep."""

    def monotonic( self ) -> float:
        return time.monotonic()

    def now_iso( self ) -> str:
        return cu.get_current_datetime_iso()

    async def sleep( self, seconds: float ) -> None:
        await asyncio.sleep( seconds )


@runtime_checkable
class CommonsGateway( Protocol ):
    """
    Injectable commons-store interaction seam (d1d4 spec §2.3).

    The poker runs server-side, in-process — it uses this gateway, NOT the
    cosa-voice MCP tool surface (that is for CC sessions).
    """
    def send_to( self, recipient: "RecipientSpec", body: str ) -> None: ...
    def last_post_ts( self, recipient: "RecipientSpec" ) -> Optional[ str ]: ...
    def read_since( self, topic: str, since_iso: str ) -> List[ dict ]: ...


class HeartbeatPokerJob( AgenticJobBase ):
    """
    Generic heartbeat poker — CJ Flow Layer-1 agentic job.

    Subclasses AgenticJobBase (and so satisfies the QueueableJob protocol by
    inheritance — see d1d4 spec §5.1). CJ Flow dispatches it to the agentic
    ThreadPoolExecutor, where it holds one pool slot for its whole lifetime.

    Exit disposition (d1d4 spec §5.4): clean / hard-cap / cancelled all RETURN
    normally from do_all() → the queue transitions the job to `done`. Only an
    unexpected exception raises → `dead`. The dead-man's-switch escalates via
    notify() and KEEPS poking — it is never a loop exit.
    """

    JOB_TYPE   = "heartbeat_poker"
    JOB_PREFIX = "hp"

    def __init__(
        self,
        recipients                : List[ RecipientSpec ],
        cadence_seconds           : int,
        termination_topic         : str,
        termination_signal_kinds  : List[ str ],
        workstream_id             : str,
        commons                   : CommonsGateway,
        deadman_consecutive_pokes : int                       = 3,
        max_duration_seconds      : int                       = 43_200,   # 12h
        clock                     : Optional[ Clock ]         = None,
        notify_fn                 : Optional[ Callable ]      = None,
        user_id      : str  = None,
        user_email   : str  = None,
        session_id   : str  = None,
        scheduled_at : str  = None,
        monopolize   : bool = False,
        debug        : bool = False,
        verbose      : bool = False,
    ) -> None:
        """
        Construct a heartbeat poker job.

        Requires:
            - recipients is a non-empty list of RecipientSpec
            - cadence_seconds is a positive int
            - max_duration_seconds is a positive int
            - deadman_consecutive_pokes is an int >= 1
            - termination_signal_kinds is a non-empty list
            - termination_topic is a non-empty string
            - commons satisfies the CommonsGateway protocol

        Ensures:
            - parent AgenticJobBase state initialised (id_hash, timestamps...)
            - config stored verbatim; injected seams resolved (clock → SystemClock)
            - any invariant violation raises ValueError with context

        Note: `notify_fn` is an injectable seam over the escalation/exit
        notifications (d1d4 spec §5.3 specified `notify_progress`; the seam is
        added so I6 can assert on notifications without emitting real ones).
        Default None → the parent AgenticJobBase.notify_progress() is used.
        """
        super().__init__(
            user_id      = user_id,
            user_email   = user_email,
            session_id   = session_id,
            scheduled_at = scheduled_at,
            monopolize   = monopolize,
            debug        = debug,
            verbose      = verbose,
        )

        # --- config validation (each branch is an I6 coverage surface) ---
        if len( recipients ) < 1:
            raise ValueError( "HeartbeatPokerJob requires at least one recipient" )
        if cadence_seconds <= 0:
            raise ValueError( f"cadence_seconds must be positive, got {cadence_seconds}" )
        if max_duration_seconds <= 0:
            raise ValueError( f"max_duration_seconds must be positive, got {max_duration_seconds}" )
        if deadman_consecutive_pokes < 1:
            raise ValueError( f"deadman_consecutive_pokes must be >= 1, got {deadman_consecutive_pokes}" )
        if len( termination_signal_kinds ) < 1:
            raise ValueError( "termination_signal_kinds must be a non-empty list" )
        if not termination_topic:
            raise ValueError( "termination_topic must be a non-empty string" )

        # --- config ---
        self.recipients                = list( recipients )
        self.cadence_seconds           = cadence_seconds
        self.termination_topic         = termination_topic
        self.termination_signal_kinds  = list( termination_signal_kinds )
        self.workstream_id             = workstream_id
        self.deadman_consecutive_pokes = deadman_consecutive_pokes
        self.max_duration_seconds      = max_duration_seconds

        # --- injected seams ---
        self._commons   = commons
        self._clock     = clock if clock is not None else SystemClock()
        self._notify_fn = notify_fn

        # --- runtime state (populated at _execute() entry) ---
        self._job_start_iso   : Optional[ str ]              = None
        self._silent_streak   : Dict[ str, int ]             = {}
        self._dms_fired       : Dict[ str, bool ]            = {}
        self._last_tick_iso   : Dict[ str, Optional[ str ] ] = {}
        self._tick_count      : int                          = 0
        self._dms_escalations : int                          = 0

        # --- unified job interface (required by queues.py done-card serializer) ---
        # The poker is a pure supervisor: it makes NO LLM calls, so it has no cost
        # to summarize. None is permanent here (cf. podcast/swe_team, which set a
        # dict after their LLM work). Without this attribute, the get-queue/done
        # serializer (queues.py: job.cost_summary) raises AttributeError once a
        # completed poker reaches the done queue.
        self.cost_summary = None

    @property
    def last_question_asked( self ) -> str:
        """Human-readable display string for the queue UI."""
        return ( f"Heartbeat poker — {self.workstream_id}: "
                 f"{len( self.recipients )} recipient(s) @ {self.cadence_seconds}s cadence" )

    # ----------------------------------------------------------------------
    # poke construction + delivery (I1)
    # ----------------------------------------------------------------------

    def _build_poke_body( self, recipient: RecipientSpec ) -> dict:
        """
        Construct the poke_body JSON envelope (design doc §4, finding F-Rio-C2).

        `kind` is the literal "heartbeat"; `workstream` from the job config;
        `role` stamped per-recipient. The poker never branches on `role`.
        """
        return {
            "kind"       : "heartbeat",
            "workstream" : self.workstream_id,
            "role"       : recipient.role,
        }

    def _deliver_tick( self ) -> None:
        """Deliver one tick's poke to every recipient; record per-recipient send time."""
        for recipient in self.recipients:
            poke_body = self._build_poke_body( recipient )
            self._commons.send_to( recipient, json.dumps( poke_body ) )
            self._last_tick_iso[ recipient.identifier ] = self._clock.now_iso()
        self._tick_count += 1

    # ----------------------------------------------------------------------
    # layered exits + escalation (I2)
    # ----------------------------------------------------------------------

    @staticmethod
    def _iso_is_after( a_iso: Optional[ str ], b_iso: Optional[ str ] ) -> bool:
        """True if timestamp `a` is strictly after `b`. Tolerant of ISO variance."""
        if a_iso is None or b_iso is None:
            return False
        try:
            return datetime.fromisoformat( a_iso ) > datetime.fromisoformat( b_iso )
        except ( ValueError, TypeError ):
            # Defensive fallback — ISO-8601 sorts lexically when same-shaped.
            return str( a_iso ) > str( b_iso )

    def _notify( self, message: str, priority: str = "high" ) -> None:
        """Fire an escalation / exit notification through the injectable seam."""
        if self._notify_fn is not None:
            self._notify_fn( message, priority )
        else:
            self.notify_progress( message, priority=priority )

    def _clean_termination_seen( self ) -> bool:
        """
        Clean-exit guard (finding F-Rio-C4): True iff a termination-signal kind
        was posted to `termination_topic` AFTER `_job_start_iso`. The
        `since=_job_start_iso` filter excludes stale signals from a prior run.
        """
        entries = self._commons.read_since( self.termination_topic, self._job_start_iso )
        for entry in entries:
            kind = ( entry.get( "metadata" ) or {} ).get( "kind" )
            if kind in self.termination_signal_kinds:
                return True
        return False

    def _detect_and_escalate( self ) -> None:
        """
        Detect each recipient's response to the PREVIOUS tick; advance the
        per-recipient silent streak; fire the dead-man's-switch once per streak.

        A poke is `answered` if the recipient's last_post_ts advanced past that
        tick's send time; otherwise `silent`. The dead-man's-switch ESCALATES
        (notify) and KEEPS poking — it never terminates the loop.
        """
        for recipient in self.recipients:
            last_tick = self._last_tick_iso[ recipient.identifier ]
            if last_tick is None:
                continue                                    # no prior tick to score
            last_post = self._commons.last_post_ts( recipient )
            if self._iso_is_after( last_post, last_tick ):
                # recipient revived — reset streak + re-arm the fired flag
                self._silent_streak[ recipient.identifier ] = 0
                self._dms_fired[ recipient.identifier ]     = False
            else:
                self._silent_streak[ recipient.identifier ] += 1
                if ( self._silent_streak[ recipient.identifier ] >= self.deadman_consecutive_pokes
                     and not self._dms_fired[ recipient.identifier ] ):
                    self._fire_deadman( recipient )

    def _fire_deadman( self, recipient: RecipientSpec ) -> None:
        """Fire the dead-man's-switch escalation for one recipient — once per streak."""
        streak = self._silent_streak[ recipient.identifier ]
        self._notify(
            f"Heartbeat poker '{self.workstream_id}': recipient '{recipient.identifier}' "
            f"({recipient.role}) has been silent for {streak} consecutive pokes — possible stall.",
            priority="high",
        )
        self._dms_fired[ recipient.identifier ] = True
        self._dms_escalations += 1

    def _exit_summary( self, reason: str ) -> str:
        """Set answer_conversational + return the exit-summary string."""
        summary = ( f"Heartbeat poker '{self.workstream_id}' exited ({reason}): "
                    f"{self._tick_count} tick(s) delivered, "
                    f"{self._dms_escalations} dead-man escalation(s)." )
        self.answer_conversational = summary
        return summary

    # ----------------------------------------------------------------------
    # the poke loop
    # ----------------------------------------------------------------------

    async def _execute( self ) -> str:
        """
        The poke loop. Each iteration, in priority order:
          1. cancellation  — AgenticJobBase.request_cancel()  → exit "cancelled"
          2. hard cap      — elapsed >= max_duration_seconds   → exit "hard_cap"
          3. clean signal  — termination kind seen after start → exit "clean"
          4. detect + escalate — score the previous tick; dead-man's-switch
          5. deliver this tick's poke to every recipient
          6. sleep one cadence

        Clean / hard-cap / cancelled all RETURN normally (→ queue marks `done`).

        Returns:
            str: the exit summary (also stored on answer_conversational)
        """
        self._job_start_iso = self._clock.now_iso()
        job_start_monotonic = self._clock.monotonic()
        for recipient in self.recipients:
            self._silent_streak[ recipient.identifier ] = 0
            self._dms_fired[ recipient.identifier ]     = False
            self._last_tick_iso[ recipient.identifier ] = None

        while True:
            # 1. cancellation
            if self._cancel_requested:
                return self._exit_summary( "cancelled" )

            # 2. hard cap — a timeout is a clean stop, not a crash (F-Rio-E4a)
            if ( self._clock.monotonic() - job_start_monotonic ) >= self.max_duration_seconds:
                self._notify(
                    f"Heartbeat poker '{self.workstream_id}' reached its "
                    f"{self.max_duration_seconds}s hard cap — stopping.",
                    priority="high",
                )
                return self._exit_summary( "hard_cap" )

            # 3. clean termination signal
            if self._clean_termination_seen():
                return self._exit_summary( "clean" )

            # 4. score the previous tick + dead-man's-switch (never an exit)
            self._detect_and_escalate()

            # 5. deliver this tick
            self._deliver_tick()

            # 6. wait one cadence
            await self._clock.sleep( self.cadence_seconds )

    def do_all( self ) -> str:
        """
        Execute the poker — sync bridge called by RunningFifoQueue.

        Bridges to the async _execute() via asyncio.run(); stamps started_at
        / completed_at from the injected clock.
        """
        self.started_at = self._clock.now_iso()
        try:
            result = asyncio.run( self._execute() )
        finally:
            self.completed_at = self._clock.now_iso()
        self.answer_conversational = result
        return result
