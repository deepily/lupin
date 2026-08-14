"""The executor seam — inline now, queues later without a rewrite.

CJ Flow v2 hands a piece of `Work` to an `Executor` and gets back an `Outcome`.
Phase 1 ships `InlineExecutor`, which runs replay and agents synchronously on
the calling thread; phase 2 will swap in a `QueuedExecutor` (a stub here that
raises) without touching a line of the flow, because the HTTP contract already
carries `status` and `job_id`. The executor is chosen by the INI key
`v2 executor` (default `inline`) via `make_executor()`.

`Work.job` is duck-typed on purpose — this module imports no agent or snapshot
class, which is exactly the machinery v2 exists to shed. Replay calls
`for_current_user()` / `run_code()` / `run_formatter()`; agents call `do_all()`.

An agent or replay that throws does **not** propagate out of the executor: it is
captured as `Outcome(status="failed", error=…)` so the flow can degrade to the
receptionist rather than letting a 500 abort an eval run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Optional, Protocol, runtime_checkable

from cosa.rest.v2.trace import StageTrace


@dataclass( frozen=True )
class Work:
    """One unit of work for an executor. Frozen — no field, and no dict, leaks.

    Requires:
        - kind is one of "replay", "agent", "receptionist".
        - job exposes the duck-typed surface the kind needs (a SolutionSnapshot
          for replay; an AgentBase subclass for agent/receptionist).

    Ensures:
        - the instance is immutable; a caller cannot rewrite it after handoff.
    """

    kind         : Literal[ "replay", "agent", "receptionist" ]
    job          : Any
    user_id      : str
    user_email   : str
    session_id   : str
    snapshotable : bool


@dataclass
class Outcome:
    """The terminal result of an executor.submit() call.

    status is "done" when an answer was produced, "parked" when a queued
    executor handed work off (phase 2), "failed" when replay or the agent threw.
    """

    status     : Literal[ "done", "parked", "failed" ]
    answer     : Optional[ str ] = None
    answer_raw : Optional[ str ] = None
    job_id     : Optional[ str ] = None
    error      : Optional[ str ] = None


@runtime_checkable
class Executor( Protocol ):
    """The one seam phase 2 swaps: submit Work + a trace, get an Outcome."""

    def submit( self, work: Work, trace: StageTrace ) -> Outcome: ...


class InlineExecutor:
    """Runs replay and agents synchronously on the calling thread.

    Requires:
        - work.kind is "replay", "agent", or "receptionist".

    Ensures:
        - replay copies the snapshot with for_current_user() before running, so
          the shared cached snapshot is never mutated (risk 3).
        - a replay/agent exception becomes Outcome(status="failed"), never a
          raised error out of submit().
        - an unrecognized work.kind raises ValueError (a programming error, not
          a runtime degradation).
    """

    def __init__( self, debug: bool=False, verbose: bool=False ) -> None:
        self.debug   = debug
        self.verbose = verbose

    def submit( self, work: Work, trace: StageTrace ) -> Outcome:
        """Dispatch by work.kind to replay or agent execution."""
        if work.kind == "replay":
            return self._replay( work, trace )
        if work.kind == "agent" or work.kind == "receptionist":
            return self._run_agent( work, trace )
        raise ValueError( f"InlineExecutor cannot handle work.kind [{work.kind}]" )

    def _replay( self, work: Work, trace: StageTrace ) -> Outcome:
        """Replay a cached snapshot on a per-user copy, formatting the answer."""
        try:
            snap   = work.job.for_current_user( work.user_id, work.session_id )
            job_id = snap.id_hash
            trace.mark( "t_replay_code" )
            snap.run_code()
            trace.mark( "t_replay_format" )
            answer = snap.run_formatter()
            return Outcome( status="done", answer=answer, answer_raw=snap.answer, job_id=job_id )
        except Exception as e:
            return Outcome( status="failed", error=str( e ) )

    def _run_agent( self, work: Work, trace: StageTrace ) -> Outcome:
        """Run an agent (or the receptionist) end-to-end via do_all()."""
        try:
            trace.mark( "t_agent" )
            answer = work.job.do_all()
            return Outcome( status="done", answer=answer, answer_raw=work.job.answer )
        except Exception as e:
            return Outcome( status="failed", error=str( e ) )


class QueuedExecutor:
    """Phase-2 stub. Pushing to the queue is not wired yet.

    Ensures:
        - submit() always raises NotImplementedError; nothing here silently
          succeeds while the queued path is absent.
    """

    def submit( self, work: Work, trace: StageTrace ) -> Outcome:
        """Always raises — the queued executor is deferred to phase 2."""
        raise NotImplementedError(
            "QueuedExecutor is a phase-2 stub — the v2 'queued' executor is not wired yet."
        )


def make_executor( name: str="inline", debug: bool=False, verbose: bool=False ) -> Executor:
    """
    Build the executor named by the INI key `v2 executor`.

    Requires:
        - name is "inline" or "queued".

    Ensures:
        - "inline"  -> a new InlineExecutor.
        - "queued"  -> a new QueuedExecutor (whose submit raises).
        - any other name raises ValueError, fail-loud rather than defaulting.
    """
    if name == "inline":
        return InlineExecutor( debug=debug, verbose=verbose )
    if name == "queued":
        return QueuedExecutor()
    raise ValueError( f"Unknown v2 executor [{name}] — expected 'inline' or 'queued'." )
