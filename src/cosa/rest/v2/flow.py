"""AskFlow — CJ Flow v2's branch logic, the thin orchestrator over parts that
already work (plan §2-§8; cascade handoff §3.B, §3.C).

Four terminal paths, in order:

    replay        cache tier-1 exact hit → replay the cached solution
    agent         router → resolve → (args complete) → run a pre-existing agent
    needs_input   args incomplete → return the first question; park if interactive
    receptionist  the else — unascertainable intent, or a degraded failure

The endpoint never waits for a human (plan §5): a missing argument parks the
request and returns the first question immediately; the human round-trip runs on
a background thread. An agent or replay that fails degrades to the receptionist
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
from cosa.rest.v2.registry import resolve
from cosa.rest.v2.trace import StageTrace

from lupin_cli.notifications.notify_user_async import notify_user_async
from lupin_cli.notifications.notification_models import AsyncNotificationRequest


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
        similarity_floor  : float                    = 100.0,
        writeback_enabled : bool                     = False,
        receptionist_factory : Callable[ ..., Any ]  = ReceptionistAgent,
        notifier          : Callable[ [ Any ], Any ] = notify_user_async,
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
        self.similarity_floor     = similarity_floor
        self.writeback_enabled    = writeback_enabled
        self.receptionist_factory = receptionist_factory
        self.notifier             = notifier
        self.trace_dir            = trace_dir
        self.debug                = debug
        self.verbose              = verbose

    # ---------------------------------------------------------------- the flow
    def run(
        self, question: str, user_id: str, user_email: str, session_id: str, websocket_id: str,
        speak: bool=True, interactive: bool=True,
    ) -> dict:
        """Route one question through cache → router → args → executor."""
        trace = StageTrace( trace_dir=self.trace_dir )
        trace.mark( "t_recv" )
        trace.update( decision_floor=self.similarity_floor, speak=speak, interactive=interactive )
        ctx = ( user_id, user_email, session_id, websocket_id, speak )

        # 1 — cache: replay only on a tier-1 exact hit (R-C1); below perfect, route.
        lookup = self.cache.lookup( question )
        self._record_lookup( trace, lookup )
        if lookup.is_replay_hit:
            work    = Work( "replay", lookup.snapshot, user_id, user_email, session_id, snapshotable=False )
            outcome = self.executor.submit( work, trace )
            if outcome.status == "done":
                return self._finish( trace, "replay", "exact_hit", outcome, question, ctx,
                                     command=lookup.snapshot.routing_command, cache_hit=True )
            return self._receptionist( trace, question, ctx, "replay_error" )

        # 2 — router.
        trace.mark( "t_router" )
        command, raw_args = self.router.route( question )
        trace.update( command=command, raw_args=raw_args )
        if command == "unknown":
            trace.set( "router_error", True )
            return self._receptionist( trace, question, ctx, "router_error" )
        spec = resolve( command )
        if spec is None:
            return self._receptionist( trace, question, ctx, "unknown_command" )

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

    # ---------------------------------------------------------------- the second turn
    def resume( self, pending_id: str, answer: str, websocket_id: str, speak: bool=True ) -> dict:
        """Fold a human's answer into a parked request and drive it to a terminal
        result — SYNCHRONOUSLY. There is no background thread; that absence is a
        permanent invariant of the design (the park site was storing a receipt,
        not a continuation, until this second turn existed).

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

        ctx        = ( entry.user_id, entry.user_email, entry.session_id, websocket_id, speak )
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
            return self._emit( trace, path="needs_input", status="parked",
                               route_reason="args_incomplete", answer=next_q, answer_raw=None,
                               command=entry.command, ctx=ctx, pending_id=pending_id,
                               args_missing=list( extraction.missing ),
                               args_known=sorted( extraction.final_args.keys() ) )

        # Complete — run the agent to a terminal result, advancing the seam.
        self.pending.set_status( pending_id, "running" )
        spec = resolve( entry.command )
        if spec is None:
            self.pending.set_status( pending_id, "failed", error="unknown_command" )
            return self._receptionist( trace, entry.question, ctx, "unknown_command" )
        result = self._run_agent( trace, spec, entry.command, entry.question, extraction.final_args, ctx, "resumed" )
        self.pending.set_status( pending_id, result[ "status" ], answer=result.get( "answer" ), error=result.get( "error" ) )
        return result

    # ---------------------------------------------------------------- helpers
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
        )

    def _build_agent( self, agent_class: Callable, agent_question: str, ctx: tuple ) -> Any:
        """Construct an agent on the shared 11-kwarg signature, bare question."""
        user_id, user_email, session_id, websocket_id, _speak = ctx
        return agent_class(
            question            = agent_question, question_gist=agent_question,
            last_question_asked = agent_question, push_counter=-1,
            user_id             = user_id, user_email=user_email, session_id=websocket_id,
            debug               = self.debug, verbose=self.verbose, auto_debug=False, inject_bugs=False,
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
        ctx: tuple, route_reason: str,
    ) -> dict:
        """Build + run a pre-existing agent; degrade to the receptionist on failure."""
        agent_question = self._compose_question( question, final_args )
        work           = Work( "agent", self._build_agent( spec.factory, agent_question, ctx ),
                               ctx[ 0 ], ctx[ 1 ], ctx[ 2 ], snapshotable=spec.snapshotable )
        outcome        = self.executor.submit( work, trace )
        if outcome.status != "done":
            return self._receptionist( trace, question, ctx, "agent_error", primary_error=outcome.error )
        return self._finish( trace, "agent", route_reason, outcome, question, ctx,
                             command=command, snapshotable=spec.snapshotable,
                             agent_class_name=spec.factory.__name__ )

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
        self, trace: StageTrace, question: str, command: str, outcome: Any, snapshotable: bool, agent_class_name: str,
    ) -> Optional[ str ]:
        """Write a v2-tagged snapshot when snapshotable+done; write_back owns the flag."""
        if not ( snapshotable and outcome.status == "done" ):
            return None
        snapshot    = self.cache.snapshot_from_result(
            question=question, answer=outcome.answer_raw, answer_conversational=outcome.answer,
            routing_command=command, agent_class_name=agent_class_name,
        )
        snapshot_id = self.cache.write_back( snapshot, writeback_enabled=self.writeback_enabled )
        if snapshot_id is not None:
            trace.mark( "t_writeback" )
        return snapshot_id

    def _finish(
        self, trace: StageTrace, path: str, route_reason: str, outcome: Any, question: str, ctx: tuple,
        command: str, cache_hit: bool=False, snapshotable: bool=False, agent_class_name: str="",
        primary_error: Optional[ str ]=None,
    ) -> dict:
        """Stamp first-useful, write back, speak, and emit the terminal result."""
        trace.mark( "t_first_useful" )
        snapshot_id = self._maybe_write_back( trace, question, command, outcome, snapshotable, agent_class_name )
        self._speak( trace, outcome.answer, outcome.job_id, ctx )
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
