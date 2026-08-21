"""AskFlow — CJ Flow v2's branch logic, the thin orchestrator over parts that
already work (plan §2-§8; cascade handoff §3.B, §3.C).

Four terminal paths, in order:

    replay        cache tier-1 exact hit → replay the cached solution
    agent         router → resolve → (args complete) → run a pre-existing agent
    needs_input   args incomplete → return the first question; park if interactive
    receptionist  the else — unascertainable intent, or a degraded failure

The endpoint never waits for a human (plan §5): a missing argument parks the
request and returns the first question immediately; the human round-trip happens
across two HTTP calls (ask then resume), each of which the router runs off the
event loop via run_in_threadpool. An agent or replay that fails degrades to the receptionist
with a distinct route_reason — never a 500, which would abort an eval run.

Every collaborator (cache, router, expeditor, executor, pending, notifier) is
injected, so the whole flow is exercised with fakes on the :7999 test path — no
live Postgres, no model server, no TTS network call. Write-back goes through the
cache's own snapshot_from_result + write_back (C2, row 41333974); the kill-switch
lives once, inside write_back — the flow only decides snapshotable-and-done.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from cosa.agents.receptionist_agent import ReceptionistAgent
from cosa.agents.runtime_argument_expeditor.agent_registry import JOB_ARG_CONTRACTS
from cosa.agents.runtime_argument_expeditor.expeditor import ArgSpec
from cosa.rest.v2.executor import Work
from cosa.rest.salutations import parse_salutations
from cosa.rest.v2.registry import resolve, resolve_agentic
from cosa.rest.v2.trace import StageTrace

from lupin_cli.notifications.notify_user_async import notify_user_async
from lupin_cli.notifications.notification_models import AsyncNotificationRequest


# The two status gates below treat these as success. A queued executor answers
# "waiting": the work was handed off, not finished and not failed.
#
# The write-back guard in _maybe_write_back is deliberately NOT one of them — it
# stays on "done" alone. A waiting job has not run, so it has no answer, and a
# cache row written from one would be an empty answer that later replays as real.
SUCCESS_STATUSES = ( "done", "waiting" )

# v1's queue-time ack, verbatim from todo_fifo_queue.py:754 (formatted at :788 and
# spoken by _notify at :855). v1 says this the moment it queues a job; the flow was
# silent at hand-off, because a waiting Outcome carries no answer and _speak returns
# early on a falsy message — so the user said something and heard nothing until the
# job finished.
STARTING_A_NEW_JOB = "New {agent_type} job..."

# The fitness gate, ported from the queue (`todo_fifo_queue._is_fit` at :364-370 and
# the reason ladder at :434-443). Rick's ruling 1: the gate moves to the flow head
# with the SAME rejection messages, and the API's 4000-char Field cap stays as the
# outer cap — this is the inner one, and it is the one the user hears about.
MAX_QUESTION_CHARS = 1000

REJECTION_EMPTY    = "Question cannot be empty"
REJECTION_TOO_LONG = "Question too long (max 1000 characters)"
REJECTION_INVALID  = "Question contains invalid content"


class AskFlow:
    """Runs one v2 request through the four branches and returns a result dict.

    Requires:
        - cache exposes lookup(question) -> CacheLookup, and (when
          writeback_enabled) snapshot_from_result(...) + write_back(snap,
          writeback_enabled=...).
        - router exposes route(question) -> (command, raw_args).
        - expeditor exposes extract(command, raw_args, question, spec) -> Extraction.
        - executor exposes submit(Work, StageTrace) -> Outcome.
        - pending exposes put()/get()/set_status() (PendingRequests).

    Ensures:
        - run() returns a result dict carrying every §8 response field and never
          raises for an agent/replay/router/extract failure — each degrades.
        - writeback_enabled with a cache missing the write-back methods raises at
          construction (fail-loud wiring, not a silent no-op).
    """

    def __init__(
        self, cache: Any, router: Any, expeditor: Any, executor: Any, pending: Any, *,
        crud_enabled      : bool,
        query_log         : Any                      = None,
        auto_debug        : bool                     = False,
        inject_bugs       : bool                     = False,
        similarity_floor  : float                    = 100.0,
        writeback_enabled : bool                     = False,
        receptionist_factory : Callable[ ..., Any ]  = ReceptionistAgent,
        notifier          : Callable[ [ Any ], Any ] = notify_user_async,
        agentic_factory   : Optional[ Callable[ ..., Any ] ] = None,
        trace_dir         : Optional[ str ]          = None,
        debug             : bool                     = False,
        verbose           : bool                     = False,
    ) -> None:
        if writeback_enabled and not ( hasattr( cache, "snapshot_from_result" ) and hasattr( cache, "write_back" ) ):
            raise ValueError( "v2 snapshot writeback enabled but the cache exposes no snapshot_from_result/write_back — fix the wiring, do not run degraded." )
        self.cache                = cache
        self.router               = router
        self.expeditor            = expeditor
        self.executor             = executor
        self.pending              = pending
        # REQUIRED, not defaulted. resolve() applies the CRUD fork and needs the live
        # flag; a default here would decide calendar and todo routing by omission,
        # which is the failure the single resolver exists to remove.
        self.crud_enabled         = crud_enabled
        # The same two INI keys the queue reads (`debug auto`, `debug inject bugs`),
        # so an agent built here gets the flags it would have got via push_job.
        # None means "do not log" — the default for every test double. Production
        # wires the real QueryLogTable in get_ask_flow.
        self.query_log            = query_log
        self.auto_debug           = auto_debug
        self.inject_bugs          = inject_bugs
        self.similarity_floor     = similarity_floor
        self.writeback_enabled    = writeback_enabled
        self.receptionist_factory = receptionist_factory
        # Builds an AGENTIC job from ( command, args ). None ⇒ lazily import the
        # factory every existing door already calls, so there is one place that knows
        # how to turn a command into a podcast job. Injectable because the real one
        # imports ten job classes and their whole dependency stacks.
        self.agentic_factory      = agentic_factory
        self.notifier             = notifier
        self.trace_dir            = trace_dir
        self.debug                = debug
        self.verbose              = verbose

    # ---------------------------------------------------------------- the flow
    def ask(
        self, question: str, user_id: str, user_email: str, session_id: str, websocket_id: str,
        speak: bool=True, interactive: bool=True,
    ) -> dict:
        """Route one question through cache → router → args → executor.

        Renamed from `run()` (Rick's entry-point ruling, 2026-08-21): the endpoint has
        been `/api/v2/ask` all along and the method finally matches its own door. The
        rename earns its churn now that `submit()` sits beside it — with two entry points
        on one flow, a method called `run` says nothing about WHICH one you are on.

        This is the only path that may reach needs-input: it is the one with a human
        waiting at the other end.
        """
        trace = StageTrace( trace_dir=self.trace_dir )
        trace.mark( "t_recv" )
        trace.update( decision_floor=self.similarity_floor, speak=speak, interactive=interactive,
                      question=question )
        ctx = ( user_id, user_email, session_id, websocket_id, speak )

        # 0 — the fitness gate, before the cache, the router or the expeditor sees it.
        # v1 rejected here and so does the flow; without it, 6c would put an unfiltered
        # question in front of the router and an empty one would route somewhere.
        rejection = self._unfit_reason( question )
        if rejection is not None:
            reason, route_reason = rejection
            trace.set( "rejected", route_reason )
            self._speak( trace, reason, None, ctx )
            return self._emit( trace, path="rejected", status="rejected", route_reason=route_reason,
                               answer=reason, answer_raw=None, command=None, ctx=ctx )

        # 1 — router, BEFORE the cache. Rick ruled the order on 2026-08-20: route first,
        # then look up. With the lookup first the flow held no command at lookup time, so
        # it structurally could not do what the queue does — running_fifo_queue skips the
        # cache for CRUD commands because the data behind them is mutable. Routing costs
        # ~22ms on a path whose cheapest observed end-to-end is over 3 seconds.
        #
        # A router_error now precedes any cache hit, on purpose: fail loud and bail, with
        # no cache fallback underneath a broken router.
        trace.mark( "t_router" )
        command, raw_args = self.router.route( question )
        trace.update( command=command, raw_args=raw_args )
        if command == "unknown":
            trace.set( "router_error", True )
            return self._receptionist( trace, question, ctx, "router_error" )
        spec = resolve( command, self.crud_enabled )
        if spec is None:
            return self._receptionist( trace, question, ctx, "unknown_command" )

        # 2 — cache: replay only on a tier-1 exact hit (R-C1); below perfect, run the agent.
        #
        # A CRUD command does not read the cache at all. The condition is DERIVED FROM THE
        # REGISTRY — a crud_factory under the live flag — not a hardcoded "todo or
        # calendar", so a seventh CRUD command later is one AgentSpec row and no edit here.
        #
        # Dormant today (tier 1 needs an exact string match) and live the moment 6a lands,
        # because gist matching is loose about wording by design: "put milk on my todo list"
        # would gist-match an earlier "what is on my todo list", the read replays, the
        # write never runs, and nothing errors.
        if self.crud_enabled and spec.crud_factory is not None:
            trace.set( "cache_skipped_crud", True )
        else:
            lookup = self.cache.lookup( question )
            self._record_lookup( trace, lookup )
            if lookup.is_replay_hit:
                work    = Work( "replay", lookup.snapshot, user_id, user_email, session_id, snapshotable=False )
                outcome = self.executor.submit( work, trace )
                # GATE 1 of 2. "waiting" means the queued executor handed the replay off —
                # success in flight, not a failure. Narrow this back to `== "done"` and a
                # cache hit routed through the queue reaches the user as the receptionist
                # apologising for a question the cache could already answer.
                if outcome.status in SUCCESS_STATUSES:
                    # Report the command the ROUTER just chose, not the matched row's
                    # `routing_command`. That column is nullable (vector_store_models.py),
                    # blank-defaulted in the SolutionSnapshot constructor and `or ""`-coerced
                    # on write, so it reported an empty string for any row whose provenance
                    # was unknown. Route-first means a real command always exists here.
                    return self._finish( trace, "replay", "exact_hit", outcome, question, ctx,
                                         command=command, cache_hit=True,
                                         agent_label=spec.label )
                return self._receptionist( trace, question, ctx, "replay_error" )

        # 3 — arguments.
        if not spec.required_args:
            return self._run_agent( trace, spec, command, question, {}, ctx, "args_none" )
        arg_spec = self._arg_spec_for( command, spec.required_args )
        trace.mark( "t_extract" )
        try:
            extraction = self.expeditor.extract( command, raw_args, question, arg_spec )
        except Exception as e:
            trace.set( "extract_error", str( e ) )
            return self._receptionist( trace, question, ctx, "extract_error" )
        trace.update( args_known=sorted( extraction.final_args.keys() ), args_missing=list( extraction.missing ) )
        if extraction.missing:
            return self._needs_input( trace, command, extraction, question, ctx, interactive )
        return self._run_agent( trace, spec, command, question, extraction.final_args, ctx, "args_complete" )

    # ---------------------------------------------------------------- the other door
    def submit(
        self, user_id: str, user_email: str, session_id: str, websocket_id: str,
        command: Optional[ str ]=None, args: Optional[ dict ]=None, question: Optional[ str ]=None,
        job: Any=None, speak: bool=True,
    ) -> dict:
        """Run work whose command is already decided — the door beside `ask`.

        WHAT IT SKIPS, AND WHY THAT IS THE DEFINITION RATHER THAN A SHORTCUT. `ask` takes
        a bare question and has to work out what it is: cache lookup, LLM routing, then
        the expeditor to pull arguments out of prose. A `submit` caller has ALREADY
        decided — it names the command and hands over the arguments, or hands over a job
        it built itself. So the whole head is skipped and this drops straight onto the
        spine `ask` shares: build, run, guarded write-back, notify. Routing a request
        whose command is already known would be paying an LLM to re-derive a fact the
        caller stated.

        TWO SHAPES, because two kinds of caller exist:
          • a NEW named job — `command` plus `args`, which is what the HTTP door sends.
          • a SAVED job being continued — `job`, an already-constructed agent, which is
            what the in-process callers hand over (a watchdog restoring from a checkpoint,
            an expediter resuming its own work). They are holding the object; making them
            describe it in a command string so this method could rebuild it would be a
            round trip through a lossy format for no gain.

        IT NEVER PARKS. `ask` may park a needs-input question because there is a human at
        the other end who will answer it. A `submit` caller is usually a service account
        or a background watchdog; parking a question at one of those means storing a
        question nobody will ever read and calling the request handled. Missing arguments
        come back as `status="needs_input"` with `args_missing` filled in — a refusal the
        caller can act on, not a suspension. **Only `ask` may reach needs-input.**

        Requires:
            - exactly one of (`command`, `job`) is supplied.
            - when `command` is supplied it resolves in the registry, and `args` carries
              every one of that command's required arguments.

        Ensures:
            - returns the same terminal dict shape `ask` returns; never raises for a
              routing or agent failure.
            - `status="waiting"` is a SUCCESS, not a degrade — a queued executor returning
              "waiting" with a job_id means the work was accepted and is running behind
              the response.
            - a snapshotable, completed result is written back through the same guarded
              path `ask` uses.

        Raises:
            - ValueError when neither or both of (`command`, `job`) are supplied. That is
              a caller bug, not a runtime condition, and a flow that guessed which one you
              meant would run the wrong work silently.
        """
        if ( command is None ) == ( job is None ):
            raise ValueError(
                "AskFlow.submit() takes exactly one of `command` (a new named job) or "
                f"`job` (a saved job being continued) — got command={command!r}, "
                f"job={job!r}."
            )

        trace = StageTrace( trace_dir=self.trace_dir )
        trace.mark( "t_recv" )
        trace.update( decision_floor=self.similarity_floor, speak=speak, interactive=False, entry="submit",
                      question=question or command or "" )
        # WHOSE WORDS THE QUERY LOG IS ABOUT TO REPORT. A `submit` caller often has no
        # question at all: the HTTP door names a command, and an in-process caller hands
        # over a job it built. The line above then files the command string — or an empty
        # string — under `query_verbatim`, and every such row went into the log typed
        # "api", exactly like a question a person typed. Nothing downstream could tell
        # them apart, so a routing command read as a thing somebody said (Pocholo, on the
        # query-log commit). `input_type` is free text with no constraint, so marking it
        # needs no migration.
        # NOT `is None`. The door's `question` field has no min_length, so "" arrives
        # as a legal value — and `question or command` above already treats it as no
        # question, filing the command string under query_verbatim. Testing for None
        # here would type that row "api" while the row it logs is a routing command
        # (Pocholo, on the mark itself).
        if not question:
            trace.set( "verbatim_source", "command" if command is not None else "job" )
        ctx = ( user_id, user_email, session_id, websocket_id, speak )

        # A job handed over whole: the caller built it, so there is nothing to resolve.
        if job is not None:
            return self._submit_prebuilt( trace, job, question or "", ctx )

        spec = resolve( command, self.crud_enabled )
        if spec is None:
            # AGENTIC COMMANDS LIVE ON A SECOND READER, and `submit` could not reach it.
            # `resolve()` is scoped to the CONVERSATIONAL class on purpose (registry
            # §5.1.3) and returns None for every agentic command — measured, not read:
            # `podcast generator`, `deep research`, `swe team` and `bug fix expediter`
            # all come back None while `math` returns a spec. So every agentic submit
            # fell straight through to the receptionist saying it did not understand a
            # command the registry knows perfectly well. That made `/api/v2/submit`
            # unable to build a single agentic job — and it is the door eleven retiring
            # endpoints are about to name in their refusals.
            agentic = resolve_agentic( command )
            if agentic is not None:
                return self._submit_agentic( trace, agentic, command, dict( args or {} ), question, ctx )
            trace.set( "unknown_command", command )
            return self._receptionist( trace, question or command, ctx, "unknown_command" )

        final_args = dict( args or {} )
        missing    = [ arg for arg in spec.required_args if not final_args.get( arg ) ]
        if missing:
            return self._submit_needs_input( trace, command, missing, sorted( final_args ), ctx )

        # NO QUESTION ⇒ NOT CACHEABLE, whatever the registry says about the command.
        # `question or command` below files the row under the command string, so a
        # question-less submit would write a cache row nothing can ever match: `ask`
        # looks rows up by the user's words, and no user says "agent router go to math".
        # A row that can never be hit is not a cache entry, it is landfill — and it
        # still costs a read on every lookup. (Pocholo, reviewing step 10.)
        return self._run_agent( trace, spec, command, question or command, final_args, ctx,
                                "submitted", snapshotable=spec.snapshotable and bool( question ) )

    def _submit_agentic(
        self, trace: StageTrace, spec: Any, command: str, args: dict,
        question: Optional[ str ], ctx: tuple,
    ) -> dict:
        """Build an agentic job from ( command, args ) and run it like any other submit.

        This is what every `/submit` endpoint did in its own handler: check the
        arguments the command declares, hand them to `create_agentic_job`, and put the
        result on the queue. Doing it here instead means the eleven doors can retire
        into one, and — the reason it matters beyond tidiness — the guarded write-back
        and the single entry point cover agentic work too.

        THE ARGUMENT CHECK IS THE SPEC'S, NOT A LIST WRITTEN HERE. `spec.required_args`
        comes off the same JOB_ARG_CONTRACTS entry the expeditor reads, so a job that
        gains a required argument gains it here with no edit.

        Requires:
            - spec is an AGENTIC AgentSpec from resolve_agentic( command )

        Ensures:
            - missing arguments return the same non-parking needs_input refusal a
              conversational submit returns; nothing is built and nothing is queued
            - a factory that cannot build the command degrades to the receptionist
              rather than raising out of the door
            - a built job runs through the SAME path as a job handed over whole, so
              there is one spelling of "run this and report it", not two
        """
        missing = [ arg for arg in spec.required_args if not args.get( arg ) ]
        if missing:
            return self._submit_needs_input( trace, command, missing, sorted( args ), ctx )

        factory = self.agentic_factory
        if factory is None:
            # Lazy: the real factory imports ten job classes. Kept out of module scope
            # so flow.py stays importable without every agent's dependency stack.
            from cosa.rest.agentic_job_factory import create_agentic_job
            factory = create_agentic_job

        user_id, user_email, session_id, _websocket_id, _speak = ctx
        try:
            job = factory(
                command    = command,
                args_dict  = args,
                user_id    = user_id,
                user_email = user_email,
                session_id = session_id,
                debug      = self.debug,
                verbose    = self.verbose,
            )
        except Exception as e:
            trace.set( "agentic_build_error", str( e ) )
            return self._receptionist( trace, question or command, ctx, "agentic_build_error",
                                       primary_error=str( e ) )
        if job is None:
            # The factory returns None for a command it does not know. The registry said
            # it was agentic, so the two tables disagree — say which command, because a
            # bare receptionist here would send the next reader hunting.
            trace.set( "agentic_build_error", f"factory returned None for {command}" )
            return self._receptionist( trace, question or command, ctx, "agentic_build_error",
                                       primary_error=f"factory returned None for {command}" )

        return self._submit_prebuilt( trace, job, question or command, ctx )

    def _submit_prebuilt( self, trace: StageTrace, job: Any, question: str, ctx: tuple ) -> dict:
        """Run a job the caller already built. No registry lookup, no argument work.

        Snapshotable is False on purpose: a caller handing over a constructed job has not
        told us the result is a reusable answer to a reusable question, and writing one
        back on a guess would put rows in the cache that `ask` would later replay.
        """
        work    = Work( "agent", job, ctx[ 0 ], ctx[ 1 ], ctx[ 2 ], snapshotable=False )
        outcome = self.executor.submit( work, trace )
        # ONE spelling of the outcome test across this file, not three. This used to read
        # `== "failed"`, which is the same idea said a third way and drifts the first time
        # a new non-success status appears — it would fall through as a success here while
        # both gates above refused it.
        if outcome.status not in SUCCESS_STATUSES:
            return self._receptionist( trace, question, ctx, "agent_error", primary_error=outcome.error )
        # `routing_command` is REQUIRED by the QueueableJob protocol (queue_protocol.py:61),
        # so read it. It used to be a getattr with an "" fallback, which would have turned a
        # job that violates the protocol into a row with a blank command — silently, and into
        # exactly the nullable blank-defaulted column this plan condemns elsewhere.
        return self._finish( trace, "agent", "submitted_prebuilt", outcome, question, ctx,
                             command=job.routing_command )

    def _submit_needs_input( self, trace: StageTrace, command: str, missing: list,
                             known: list, ctx: tuple ) -> dict:
        """Refuse an under-specified submit — WITHOUT parking it.

        `ask`'s `_needs_input` stores a pending entry and asks the human the first
        question. Doing that here would park a question at a service account: the entry
        would sit until it expired, the caller would get a `pending_id` it has no way to
        answer, and the request would read as handled. So this returns the same shape
        minus the park — no `pending_id`, nothing stored, `status="needs_input"`.
        """
        trace.mark( "t_first_useful" )
        trace.update( args_missing=missing, args_known=known )
        return self._emit( trace, path="needs_input", status="needs_input",
                           route_reason="args_incomplete_no_park", answer=None, answer_raw=None,
                           command=command, ctx=ctx, pending_id=None,
                           args_missing=missing, args_known=known )

    # ---------------------------------------------------------------- the second turn
    def resume( self, pending_id: str, answer: str, websocket_id: str, speak: bool=True ) -> dict:
        """Fold a human's answer into a parked request and drive it to a terminal
        result, on the caller's thread.

        This method spawns NO background thread of its own, and that remains a
        design invariant: the park site stores a continuation, and this second turn
        runs it to completion rather than handing it to a worker and returning early.

        What CHANGED is the caller: routers/v2_ask.py now awaits this through
        run_in_threadpool, so it executes on a worker thread instead of the event
        loop. The docstring used to say "SYNCHRONOUSLY... no background thread",
        which read as a promise that no thread is involved anywhere — untrue the
        moment the handler moved off the loop, and exactly the kind of stale
        sentence a reader trusts.

        Requires:
            - pending_id identifies a parked entry; answer is the human's reply to
              that entry's FIRST missing argument.

        Ensures:
            - a missing/expired pending_id REFUSES loudly (status='expired',
              route_reason='pending_expired') — never a 500, never a silent no-op.
            - the answer fills the first missing arg; if more remain, the SAME
              pending_id is re-asked (status stays 'pending'); if complete, the
              agent runs and the entry advances pending -> running -> done|failed
              (the AI-observable completion seam).
        """
        trace = StageTrace( trace_dir=self.trace_dir )
        trace.mark( "t_recv" )
        trace.set( "pending_id", pending_id )

        entry = self.pending.get( pending_id )
        if entry is None:
            trace.set( "resume_error", "pending_expired_or_unknown" )
            return self._emit( trace, path="needs_input", status="expired",
                               route_reason="pending_expired", answer=None, answer_raw=None,
                               command=None, ctx=( "", "", "", websocket_id, speak ),
                               pending_id=pending_id )

        ctx = ( entry.user_id, entry.user_email, entry.session_id, websocket_id, speak )
        # The question lives on the pending entry, so this is the FIRST point in resume
        # where there is one to stamp. Without it the query log writes a blank question
        # for every resumed turn (Pocholo, on 58f73b32) — v1 logged it on this path too.
        # The expired-refusal exit above is the one case with genuinely nothing to name.
        trace.update( question=entry.question )

        # Claim the whole TURN atomically. Everything below is a read-modify-write on
        # the entry's extraction, and it must have exactly one owner.
        #
        # Two things go wrong without this, and only the first needs concurrency.
        # (a) A SECOND resume of a COMPLETED conversation reached
        #     `extraction.missing[ 0 ]` on an empty list and raised IndexError — a
        #     500 from the one path whose contract says it never 500s. Reachable at
        #     HEAD with no threading at all: the entry lives until its TTL, so a
        #     retry or a double-clicked answer hit it.
        # (b) Two CONCURRENT resumes of a multi-argument interview both fold an
        #     answer into the same extraction. That does not merely lose an answer,
        #     it puts answers in the WRONG SLOTS: racing a location+date interview
        #     produced {"location": "Tuesday", "date": "Boston"} in four runs of six.
        #     Unreachable while this handler ran on the event loop; reachable the
        #     moment it moved to a worker thread, which is this same commit.
        if self.pending.claim( pending_id ) is None:
            trace.set( "resume_error", "already_resumed" )
            return self._emit( trace, path="needs_input", status="expired",
                               route_reason="already_resumed", answer=None, answer_raw=None,
                               command=entry.command, ctx=ctx, pending_id=pending_id )

        extraction = entry.extraction
        first_arg  = extraction.missing[ 0 ]
        extraction.final_args[ first_arg ] = answer
        extraction.missing = [ m for m in extraction.missing if m != first_arg ]
        trace.update( args_known=sorted( extraction.final_args.keys() ), args_missing=list( extraction.missing ) )

        if extraction.missing:
            # Interview continues — re-ask the next arg on the SAME pending_id.
            next_arg = extraction.missing[ 0 ]
            next_q   = extraction.fallback_questions.get( next_arg ) or f"What {next_arg} would you like?"
            trace.mark( "t_first_useful" )
            self._speak( trace, next_q, None, ctx )
            # The turn is over and the conversation is answerable again — hand it
            # back, or every turn after the first would be refused as already_resumed.
            self.pending.release_turn( pending_id )
            return self._emit( trace, path="needs_input", status="parked",
                               route_reason="args_incomplete", answer=next_q, answer_raw=None,
                               command=entry.command, ctx=ctx, pending_id=pending_id,
                               args_missing=list( extraction.missing ),
                               args_known=sorted( extraction.final_args.keys() ) )

        # Complete — run the agent to a terminal result, advancing the seam. This
        # turn already owns the conversation (claimed above), so no second claim is
        # needed here; "answering" advances to "running".
        self.pending.set_status( pending_id, "running" )
        spec = resolve( entry.command, self.crud_enabled )
        if spec is None:
            self.pending.set_status( pending_id, "failed", error="unknown_command" )
            return self._receptionist( trace, entry.question, ctx, "unknown_command" )
        result = self._run_agent( trace, spec, entry.command, entry.question, extraction.final_args, ctx, "resumed" )
        self.pending.set_status( pending_id, result[ "status" ], answer=result.get( "answer" ), error=result.get( "error" ) )
        return result

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _unfit_reason( question: str ):
        """
        Why this question is refused, or None if it is fit to process.

        The three rules and their wording are v1's, kept verbatim so a user who
        hears a refusal today hears the same one after the switch. Returns the
        spoken reason AND a route_reason, so the trace records WHICH rule fired
        rather than a single flat "rejected".
        """
        if not question or not question.strip():
            return ( REJECTION_EMPTY, "empty_question" )
        if len( question ) > MAX_QUESTION_CHARS:
            return ( REJECTION_TOO_LONG, "question_too_long" )
        if question.lower().startswith( "invalid" ):
            return ( REJECTION_INVALID, "invalid_content" )
        return None

    def _log_query( self, trace: StageTrace, ctx: tuple, snapshot_id, cache_hit: bool ) -> None:
        """
        Write this request to the query log — v1's `_log_query_with_results`, which
        had five call sites in push_job and no v2 equivalent at all.

        Rick's ruling 19: the flow writes it. Without this the query log stops being
        written for voice traffic the moment 6c lands, and nothing would say so — the
        table would simply stop growing.

        ONE call site, at the terminal chokepoint, where v1 had five. Every exit
        funnels through _emit, so a refusal, a needs-input park and an answered
        question are all logged, which v1's five scattered calls did not manage.

        A logging failure NEVER breaks a request: v1 swallowed with a debug print and
        so does this. A user's question must not 500 because an analytics row could
        not be written.

        TWO FIELDS ARE DELIBERATELY ABSENT, and both are recorded here rather than
        filled with something that would read as fact:

          · `embeddings` — CacheLookup does not return the vectors, and v2 skips
            embedding entirely on a tier-1 exact hit. Generating them to log them
            would re-add the exact cost v2 exists to avoid.
          · `cache_hits` — v1's two flags mean "an embedding was generated and came
            back non-empty", which is NOT what v2's `embed_cached` reports. Putting
            one fact under the other's column name is the same class of quiet
            wrongness as a question_gist that is really the question.
        """
        if self.query_log is None:
            return
        try:
            user_id, _user_email, _session_id, websocket_id, _speak = ctx
            question   = trace.fields.get( "question" ) or ""
            stripped   = parse_salutations( question )[ 1 ]
            timings    = trace.timings_ms()
            similarity = trace.fields.get( "similarity" )
            verbatim_source = trace.fields.get( "verbatim_source" )
            input_type      = "api" if verbatim_source is None else f"api-{verbatim_source}"
            self.query_log.log_query(
                query_verbatim     = question,
                query_normalized   = trace.fields.get( "question_normalized" ) or self.cache.normalize( stripped ),
                query_gist         = self.cache.gist( stripped ),
                user_id            = user_id,
                session_id         = websocket_id,
                # 'voice' / 'text' / 'api' is v1's vocabulary (query_log_table.py:84) and
                # the column is free text. A row whose verbatim is not a person's words
                # says so here — "api-command" or "api-job" — rather than passing for one.
                input_type         = input_type,
                match_result       = {
                    "snapshot_id" : ( snapshot_id or "" ) if not cache_hit else ( trace.fields.get( "job_id" ) or snapshot_id or "" ),
                    "type"        : "exact_match" if cache_hit else "no_match_new_agent",
                    "confidence"  : similarity if cache_hit and similarity is not None else 0.0,
                },
                processing_time_ms = int( timings.get( "t_complete" ) or 0 ),
            )
        except Exception as e:
            if self.debug: print( f"[v2] query log write failed: {e}" )

    def _record_lookup( self, trace: StageTrace, lookup: Any ) -> None:
        """Stamp the cache's own timings + score fields onto the trace."""
        trace.update(
            cache_tier=lookup.tier, similarity=lookup.similarity, best_score=lookup.best_score,
            cache_candidate=lookup.best_candidate is not None, embed_cached=lookup.embed_cached,
            question_normalized=lookup.question_normalized, t_exact_ms=lookup.t_exact_ms,
            t_embed_ms=lookup.t_embed_ms, t_ann_ms=lookup.t_ann_ms,
        )

    def _arg_spec_for( self, command: str, required: tuple ) -> ArgSpec:
        """Build the expeditor ArgSpec: from the table, or synthesized (weather)."""
        entry = JOB_ARG_CONTRACTS.get( command )
        if entry is not None:
            return ArgSpec.from_entry( entry )
        # Not in JOB_ARG_CONTRACTS (weather): synthesize at the call site — do NOT add
        # a table entry (R-B3, María's line). fallback_questions drives extract()'s
        # user_visible computation for a command with no CLI.
        return ArgSpec(
            arg_mapping        = {},
            system_provided    = [],
            required_user_args = list( required ),
            fallback_questions = { arg: f"What {arg} would you like?" for arg in required },
            fallback_defaults  = {},
            special_handlers   = {},
            display_name       = command.replace( "agent router go to ", "" ).title(),
            cli_module         = None,
            file_args          = {},   # weather takes no file-typed argument
        )

    def _build_agent( self, agent_class: Callable, agent_question: str, ctx: tuple,
                      question: Optional[ str ]=None ) -> Any:
        """Construct an agent the way the queue constructs one (step 4 parity).

        `question` is the user's ORIGINAL text; `agent_question` is that text with
        the expeditor's extracted values folded in. Both are needed: the gist and
        the salutation are read off the original, while the agent itself is asked
        the composed one.

        Five kwargs are real parity with push_job (`todo_fifo_queue.py:782-787`):
        question_gist, debug, verbose, auto_debug, inject_bugs. THREE are deliberate
        non-matches, each ruled and each recorded here so nobody has to re-derive
        why the table does not line up:

          · `question` — the flow passes the COMPOSED question. Bare parity would
            drop the arguments the expeditor extracted, because v1 never ran the
            expeditor for conversational commands and the agent re-parsed the raw
            text itself. Matching here would regress R-B4.

          · `last_question_asked` — the flow passes the INTENDED form, salutation
            plus the stripped question. v1 builds `salutations + " " + question`
            from the ORIGINAL, which still contains the salutation, so "hey what is
            the weather" reaches every agent as "hey hey what is the weather".
            Measured against the real method, not read off the source. Parity here
            would mean copying a defect.

          · `push_counter` — v1's counter lives on the queue singleton, which the
            flow cannot see without reading through the executor into its queue —
            the coupling the executor seam exists to prevent, and absent entirely on
            the inline executor. Stays -1; it rides to step 12 with the lifespan
            wiring.

        `debug=True` / `verbose=False` are v1's literals, not the flow's own flags:
        push_job hardcodes them and ignores the queue's, so an agent that ran
        verbose under v1 must keep running verbose here.
        """
        user_id, user_email, session_id, websocket_id, _speak = ctx
        original            = question if question is not None else agent_question
        salutation, stripped = parse_salutations( original )
        return agent_class(
            question            = agent_question,
            question_gist       = self.cache.gist( stripped ),
            last_question_asked = f"{salutation} {stripped}".strip(),
            push_counter        = -1,
            user_id             = user_id, user_email=user_email, session_id=websocket_id,
            debug               = True, verbose=False,
            auto_debug          = self.auto_debug, inject_bugs=self.inject_bugs,
        )

    def _compose_question( self, question: str, final_args: dict ) -> str:
        """Fold extracted arg values into the question so the agent re-parses them (R-B4)."""
        composed = question
        for value in final_args.values():
            if value and str( value ).lower() not in composed.lower():
                composed = f"{composed} {value}"
        return composed

    def _run_agent(
        self, trace: StageTrace, spec: Any, command: str, question: str, final_args: dict,
        ctx: tuple, route_reason: str, snapshotable: Optional[ bool ]=None,
    ) -> dict:
        """Build + run a pre-existing agent; degrade to the receptionist on failure.

        `snapshotable` defaults to the registry's answer for this command. A caller
        passes it only to say NO more strongly than the registry does — `submit`
        does that when it has no question to file the row under.
        """
        may_cache      = spec.snapshotable if snapshotable is None else snapshotable
        agent_question = self._compose_question( question, final_args )
        work           = Work( "agent", self._build_agent( spec.factory, agent_question, ctx, question ),
                               ctx[ 0 ], ctx[ 1 ], ctx[ 2 ], snapshotable=may_cache )
        outcome        = self.executor.submit( work, trace )
        # GATE 2 of 2. Same reason as gate 1, on the ordinary path: narrow this back
        # to `!= "done"` and EVERY queued job degrades to the receptionist the moment
        # it is handed off, while the real agent still runs behind it.
        if outcome.status not in SUCCESS_STATUSES:
            return self._receptionist( trace, question, ctx, "agent_error", primary_error=outcome.error )
        return self._finish( trace, "agent", route_reason, outcome, question, ctx,
                             command=command, snapshotable=may_cache,
                             agent_class_name=spec.factory.__name__, agent_label=spec.label )

    def _receptionist( self, trace: StageTrace, question: str, ctx: tuple, route_reason: str,
                       primary_error: Optional[ str ]=None ) -> dict:
        """The else — run the receptionist inline (its failure is terminal, no recursion).

        primary_error carries the FAILURE THAT CAUSED THE DEGRADE. Without it the
        emitted error is the fallback's, and a live failure reports why the
        receptionist died while saying nothing about why the real agent did — which
        is a fallback that hides the fault it was reached by.
        """
        if primary_error: trace.set( "primary_agent_error", primary_error )
        work    = Work( "receptionist", self._build_agent( self.receptionist_factory, question, ctx ),
                       ctx[ 0 ], ctx[ 1 ], ctx[ 2 ], snapshotable=False )
        outcome = self.executor.submit( work, trace )
        return self._finish( trace, "receptionist", route_reason, outcome, question, ctx,
                             command="agent router go to receptionist", primary_error=primary_error )

    def _needs_input(
        self, trace: StageTrace, command: str, extraction: Any, question: str,
        ctx: tuple, interactive: bool,
    ) -> dict:
        """Args incomplete: return the first question; park + resume when interactive."""
        first_arg  = extraction.missing[ 0 ]
        first_q    = extraction.fallback_questions.get( first_arg ) or f"What {first_arg} would you like?"
        trace.mark( "t_first_useful" )
        pending_id = None
        if interactive:
            pending_id = self.pending.put( extraction=extraction, user_email=ctx[ 1 ], session_id=ctx[ 2 ],
                                           user_id=ctx[ 0 ], command=command, question=question )
            trace.set( "pending_id", pending_id )
        self._speak( trace, first_q, None, ctx )
        return self._emit( trace, path="needs_input", status=( "parked" if interactive else "needs_input" ),
                           route_reason="args_incomplete", answer=first_q, answer_raw=None, command=command,
                           ctx=ctx, pending_id=pending_id, args_missing=list( extraction.missing ),
                           args_known=sorted( extraction.final_args.keys() ) )

    def _maybe_write_back(
        self, trace: StageTrace, question: str, command: str, outcome: Any, snapshotable: bool,
        agent_class_name: str, ctx: tuple,
    ) -> Optional[ str ]:
        """Write a v2-tagged snapshot when snapshotable+done; write_back owns the flag.

        ctx carries the identity this write belongs to. It was always in scope at
        the call site and simply was not passed, so every v2 write-back produced a
        row with no owner.
        """
        if not ( snapshotable and outcome.status == "done" ):
            return None
        user_id, user_email, session_id, websocket_id, _speak = ctx
        snapshot    = self.cache.snapshot_from_result(
            question=question, answer=outcome.answer_raw, answer_conversational=outcome.answer,
            routing_command=command, agent_class_name=agent_class_name,
            user_id=user_id, session_id=session_id,
        )
        snapshot_id = self.cache.write_back( snapshot, writeback_enabled=self.writeback_enabled )
        if snapshot_id is not None:
            trace.mark( "t_writeback" )
        return snapshot_id

    def _finish(
        self, trace: StageTrace, path: str, route_reason: str, outcome: Any, question: str, ctx: tuple,
        command: str, cache_hit: bool=False, snapshotable: bool=False, agent_class_name: str="",
        primary_error: Optional[ str ]=None, agent_label: Optional[ str ]=None,
    ) -> dict:
        """Stamp first-useful, write back, speak, and emit the terminal result."""
        trace.mark( "t_first_useful" )
        snapshot_id = self._maybe_write_back( trace, question, command, outcome, snapshotable, agent_class_name, ctx )
        self._speak( trace, self._spoken_line( outcome, agent_label ), outcome.job_id, ctx )
        return self._emit(
            trace, path=path, status=outcome.status, route_reason=route_reason, answer=outcome.answer,
            answer_raw=outcome.answer_raw, command=command, ctx=ctx, job_id=outcome.job_id,
            snapshot_id=snapshot_id, cache_hit=cache_hit,
            error=self._compose_error( primary_error, outcome.error ),
        )

    @staticmethod
    def _compose_error( primary_error: Optional[ str ], fallback_error: Optional[ str ] ) -> Optional[ str ]:
        """Keep the CAUSE of the degrade in the emitted error, not just the fallback's."""
        if not primary_error: return fallback_error
        if not fallback_error: return f"primary agent failed: {primary_error}"
        return f"primary agent failed: {primary_error} | receptionist: {fallback_error}"

    @staticmethod
    def _spoken_line( outcome: Any, agent_label: Optional[ str ] ) -> Optional[ str ]:
        """What this exit says out loud: the answer, or v1's ack when the work was queued.

        A queued job has no answer yet, so `waiting` speaks the ack INSTEAD of the
        answer — never as well as. That is what keeps it to exactly one spoken line
        per request whichever executor is wired.

        Returns None when a waiting outcome has no label to name. The receptionist
        is the case: v1 does not say "New … job" for it either — it speaks a random
        hemming-and-hawing line built from word lists that live on the queue
        (todo_fifo_queue.py:217-220, spoken at :807 and :837). Reproducing that here
        would move queue-owned state into the flow, so it is left for its own
        decision rather than invented.
        """
        if outcome.status != "waiting":
            return outcome.answer
        if not agent_label:
            return None
        return STARTING_A_NEW_JOB.format( agent_type=agent_label )

    def _speak( self, trace: StageTrace, message: Optional[ str ], job_id: Optional[ str ], ctx: tuple ) -> None:
        """Dispatch TTS via the injected notifier when speak is on; stamp t_tts_dispatch."""
        if not ctx[ 4 ] or not message:
            return
        self.notifier( AsyncNotificationRequest(
            message=message, notification_type="task", priority="high", suppress_ding=True,
            target_user=ctx[ 1 ], job_id=job_id, sender_id="ask.flow@lupin.deepily.ai",
        ) )
        trace.mark( "t_tts_dispatch" )

    def _emit( self, trace: StageTrace, *, path: str, status: str, route_reason: str, answer: Optional[ str ],
               answer_raw: Optional[ str ], command: Optional[ str ], ctx: tuple, job_id: Optional[ str ]=None,
               snapshot_id: Optional[ str ]=None, pending_id: Optional[ str ]=None,
               cache_hit: bool=False, args_known: Optional[ list ]=None, args_missing: Optional[ list ]=None,
               error: Optional[ str ]=None ) -> dict:
        """Assemble the §8 response dict and write the authoritative trace line.

        Stamps t_complete here — the single chokepoint every terminal exit funnels
        through (agent/replay/receptionist via _finish, needs_input, resume's
        interview-continue, and the expired refusal). This makes t_recv -> t_complete
        the completion-symmetric span for v1's RUNNING->COMPLETED (report note, not a
        gate; row 76a3c32d). Because _finish calls _maybe_write_back BEFORE _emit,
        t_complete is always stamped after the snapshot write. It follows _speak on the
        answer path, so a few microseconds of TTS-dispatch land inside v2's span — a
        conservative bias (v2 reads slightly slower, never faster), the audit-safe
        direction for the paired harness.
        """
        trace.mark( "t_complete" )
        trace.update( path=path, status=status, route_reason=route_reason, cache_hit=cache_hit,
                      wrote_snapshot=snapshot_id is not None )
        trace.write()
        self._log_query( trace, ctx, snapshot_id=snapshot_id, cache_hit=cache_hit )
        return {
            "path"        : path,           "status"       : status,        "route_reason" : route_reason,
            "answer"      : answer,         "answer_raw"   : answer_raw,     "command"      : command,
            "args_known"  : args_known or [], "args_missing": args_missing or [],
            "pending_id"  : pending_id,     "job_id"       : job_id,         "snapshot_id"  : snapshot_id,
            "similarity"  : trace.fields.get( "similarity" ),               "wrote_snapshot": snapshot_id is not None,
            "cache_hit"   : cache_hit,      "spoke"        : trace.has_mark( "t_tts_dispatch" ),
            "timings_ms"  : trace.timings_ms(),                             "trace_id"     : trace.trace_id,
            "error"       : error,
        }
