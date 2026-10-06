"""The executor seam — inline now, queues later without a rewrite.

CJ Flow v2 hands a piece of `Work` to an `Executor` and gets back an `Outcome`.
`InlineExecutor` runs replay and agents synchronously on the calling thread;
`QueuedExecutor` hands them to the existing FIFO queue and answers `waiting`.
Swapping one for the other touches no line of the flow, because the HTTP
contract already carries `status` and `job_id`. The INI key `v2 executor` (default
`inline`) picks the executor, through `make_executor()`.

`Work.job` is duck-typed. This module imports no agent or snapshot class, because that
is the machinery v2 exists to shed. Replay calls `for_current_user()`, `run_code()` and
`run_formatter()`. Agents call `do_all()`.

An agent or replay that throws does **not** propagate out of the executor. The executor
captures it as `Outcome(status="failed", error=…)`. The flow can then degrade to the
receptionist, rather than letting a 500 abort an eval run.
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

    status is "done" when an answer was produced. It is "waiting" when the queued
    executor handed work off. It is "failed" when replay or the agent threw.

    "waiting" is not "parked". A job sitting in the queue is waiting its turn.
    Nobody suspended it and nothing is owed to it. "parked" is kept for the flow's
    needs-input path, where a request is suspended pending an answer from the user.
    """

    status     : Literal[ "done", "waiting", "failed" ]
    answer     : Optional[ str ] = None
    answer_raw : Optional[ str ] = None
    job_id     : Optional[ str ] = None
    error      : Optional[ str ] = None
    # THE CODE THE AGENT GENERATED, carried out so the write-back can persist it.
    # Without these three the cache wrote rows with empty code, and SolutionSnapshot's
    # run_code() raises "Cannot execute empty code list" for every class but the
    # codeless ones — so a v2-written MathAgent row could be written and never served
    # (bug 38815328: 117 of 300 warm-pass requests came back as the receptionist).
    # None means "this agent produced no code", which is not the same as an empty list:
    # the snapshot constructor's own defaults stand rather than being overwritten.
    code         : Optional[ list ] = None
    code_example : Optional[ str ]  = None
    code_returns : Optional[ str ]  = None
    # WHERE THE QUEUED JOB SITS, right after the push: the todo queue's size at that moment
    # (row a3c59f2d, Rick 2026-09-29 — door 18 retires once v2 reports this). It is the
    # same number `/api/test-suite/submit` returned as `queue_position`, and like it a
    # SNAPSHOT: it is not kept current as the queue moves. None on every path that queued
    # nothing (inline, replay, failure).
    queue_position : Optional[ int ] = None


@runtime_checkable
class Executor( Protocol ):
    """The seam to swap: submit Work and a trace, get an Outcome."""

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
            # work.user_email is passed, not merely carried: without it the replay copy
            # keeps the STORED (empty) address and `_notify` returns before TTS, which is
            # the missing-spoken-answer half of row `0e7c9214`.
            snap   = work.job.for_current_user( work.user_id, work.session_id,
                                                user_email=work.user_email )
            job_id = snap.id_hash
            trace.mark( "t_replay_code" )
            snap.run_code()
            trace.mark( "t_replay_format" )
            answer = snap.run_formatter()
            return Outcome( status="done", answer=answer, answer_raw=snap.answer, job_id=job_id )
        except Exception as e:
            return Outcome( status="failed", error=str( e ) )

    @staticmethod
    def _generated_code( job: Any ) -> tuple:
        """The (code, example, returns) this agent produced, or three Nones.

        v1's `SolutionSnapshot.create_from_agent` reads these three keys off
        `prompt_response_dict`. The v2 write-back must read them too. Otherwise the
        written row has empty code and cannot be replayed.

        `AgentBase.run_prompt()` sets `prompt_response_dict`, not `__init__`. An agent
        that answered without running a prompt does not have one. The `hasattr` check
        is that stated condition, not attribute fishing. It yields no code. Reading the
        attribute unguarded would raise inside the caller's try and report a successful
        agent as failed.
        """
        if not hasattr( job, "prompt_response_dict" ):
            return ( None, None, None )
        response = job.prompt_response_dict
        return ( response.get( "code" ), response.get( "example" ), response.get( "returns" ) )

    def _run_agent( self, work: Work, trace: StageTrace ) -> Outcome:
        """Run an agent (or the receptionist) end-to-end via do_all()."""
        try:
            trace.mark( "t_agent" )
            answer = work.job.do_all()
            code, code_example, code_returns = self._generated_code( work.job )
            return Outcome( status="done", answer=answer, answer_raw=work.job.answer,
                            code=code, code_example=code_example, code_returns=code_returns )
        except Exception as e:
            return Outcome( status="failed", error=str( e ) )


class QueuedExecutor:
    """Hands the work to the existing FIFO queue instead of running it here.

    This is the v1 tail of `push_job` in `src/cosa/rest/todo_fifo_queue.py`: scope the id,
    push onto the todo queue, answer `waiting`. The queue consumer runs the job later and the websocket carries the result.
    The flow's two status gates treat `waiting` as success; the write-back guard does not.

    Requires:
        - todo_queue exposes push( job ) and a user_job_tracker carrying
          register_scoped_job( base_hash, user_id, session_id ).

    Ensures:
        - the job's id_hash is the scoped id before the push, which is v1's
          order: a filtering read must never see an unscoped row.
        - returns Outcome( status="waiting", job_id=<scoped id>, queue_position=<the todo
          queue's size right after the push> ) with no answer.
        - a queue that refuses the push is captured as Outcome(status="failed"),
          the same contract InlineExecutor keeps — the flow degrades to the
          receptionist rather than letting a 500 out of the request.
    """

    def __init__( self, todo_queue: Any, debug: bool=False, verbose: bool=False ):
        if todo_queue is None:
            raise ValueError(
                "QueuedExecutor needs the todo queue — pass make_executor( 'queued', "
                "todo_queue=… ). Step 12 builds it in lifespan and hangs it on app.state."
            )
        self.todo_queue = todo_queue
        self.debug      = debug
        self.verbose    = verbose

    def submit( self, work: Work, trace: StageTrace ) -> Outcome:
        """Scope the job, push it, and answer waiting, for every kind of work."""
        try:
            trace.mark( "t_enqueue" )
            job         = work.job
            # Address the job to whoever is asking NOW (row `0e7c9214`). A snapshot
            # loaded from storage carries whoever asked FIRST, and this pushed it
            # verbatim — so the completion frame went to an old-format user_id nobody
            # holds a session under, and the EMPTY stored email made `_notify` return
            # before TTS. Both symptoms Rick reported, one omission.
            #
            # `Work` has always carried both fields; until now neither was READ in this
            # module, which is what an unused dataclass field usually means.
            #
            # Falsy means "no requester context", never "blank it out" — an erased
            # identity is as undeliverable as a stale one.
            if work.user_id:    job.user_id    = work.user_id
            if work.user_email: job.user_email = work.user_email
            job.id_hash = self.todo_queue.user_job_tracker.register_scoped_job(
                job.id_hash, work.user_id, work.session_id
            )
            # Lineage (row 4cbd4858): an ask made on behalf of a monopolizing job carries that
            # job's id on the trace; stamping it is what lets Gate B admit this job through
            # the hold. Absent, the job is untouched and stays foreign, exactly as before.
            parent_id_hash = trace.fields.get( "parent_id_hash" )
            if parent_id_hash: job.spawned_by_id_hash = parent_id_hash
            self.todo_queue.push( job )
            # READ THE POSITION AFTER THE PUSH, IN ITS OWN GUARD. The push has succeeded, so
            # the job IS queued; a size() that raises must not reach the `except` below and
            # report a queued job as failed (the flow would then degrade to the receptionist
            # while the job ran on unseen). A position that cannot be read is just None.
            try:
                queue_position = self.todo_queue.size()
            except Exception:
                queue_position = None
            if self.debug: print( f"[v2] queued [{work.kind}] as [{job.id_hash}]" )
            return Outcome( status="waiting", job_id=job.id_hash, queue_position=queue_position )
        except Exception as e:
            return Outcome( status="failed", error=str( e ) )


def make_executor( name: str="inline", todo_queue: Any=None, debug: bool=False,
                   verbose: bool=False ) -> Executor:
    """
    Build the executor named by the INI key `v2 executor`.

    Requires:
        - name is "inline" or "queued".
        - todo_queue is the todo FIFO queue when name is "queued"; it is unused
          by "inline".

    Ensures:
        - "inline"  -> a new InlineExecutor.
        - "queued"  -> a new QueuedExecutor bound to todo_queue.
        - "queued" with no queue raises ValueError naming the fix, rather than
          building an executor that fails later on the live path.
        - any other name raises ValueError, fail-loud rather than defaulting.
    """
    if name == "inline":
        return InlineExecutor( debug=debug, verbose=verbose )
    if name == "queued":
        return QueuedExecutor( todo_queue, debug=debug, verbose=verbose )
    raise ValueError( f"Unknown v2 executor [{name}] — expected 'inline' or 'queued'." )
