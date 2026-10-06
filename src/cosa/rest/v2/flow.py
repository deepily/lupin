"""AskFlow, CJ Flow v2's branch logic: a thin orchestrator over parts that already work.

A request ends on one of four paths, tried in this order:

    - replay: cache exact hit, replay the cached solution
    - agent: router, resolve, then run a pre-existing agent once the arguments are complete
    - needs_input: arguments incomplete, return the first question and park the request if interactive
    - receptionist: the else branch, for unascertainable intent or a degraded failure

The endpoint never waits for a human. A missing argument parks the request and returns the first question at once.
The human answers in a second HTTP call (resume). The router runs each call off the event loop with run_in_threadpool.
An agent or replay that fails degrades to the receptionist with a distinct route_reason. It never returns a 500, which would abort an eval run.

Every collaborator (cache, router, expeditor, executor, pending, notifier) is injected.
The whole flow therefore runs with fakes on the :7999 test path: no live Postgres, no model server, no TTS network call.
Write-back goes through the cache's own snapshot_from_result and write_back. The kill-switch lives once, inside write_back.
The flow only decides whether a result is snapshotable and done.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from cosa.agents.receptionist_agent import ReceptionistAgent
from cosa.memory.solution_snapshot import CODELESS_AGENT_CLASSES
from cosa.agents.runtime_argument_expeditor.agent_registry import JOB_ARG_CONTRACTS
from cosa.agents.runtime_argument_expeditor.expeditor import ArgSpec
from cosa.rest.v2.executor import Work
from cosa.rest.v2.near_match_guard import quantities_differ
from cosa.rest.v2.refusal import SubmitRefused
from cosa.rest.salutations import parse_salutations
import difflib
from cosa.rest.v2.registry import resolve, resolve_agentic, canonical_command
from cosa.rest.v2.source_document import SOURCE_DOCUMENT_ARG, validate_source_documents
from cosa.rest.v2.trace import StageTrace

from lupin_cli.notifications.notify_user_async import notify_user_async
from lupin_cli.notifications.notify_user_sync import notify_user_sync
from lupin_cli.notifications.notification_models import AsyncNotificationRequest, NotificationRequest, ResponseType


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

# The near-match confirmation, verbatim from the queue (todo_fifo_queue.py:620-643):
# same sentence, same YES_NO shape, same 30s timeout defaulting to "no", same retry
# ladder. A user who hears this prompt today must hear the same one after the switch.
CONFIRMATION_QUESTION = "Is that the same as: {question}?"

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
        - ask() returns a result dict carrying every response field and never
          raises for an agent/replay/router/extract failure; each degrades.
        - writeback_enabled with a cache missing the write-back methods raises at
          construction (fail-loud wiring, not a silent no-op).
    """

    def __init__(
        self, cache: Any, router: Any, expeditor: Any, executor: Any, pending: Any, *,
        crud_enabled      : bool,
        confirmation_threshold : Optional[ float ]   = None,
        confirmation_enabled   : bool                = True,
        confirmer         : Callable[ ..., Any ]     = notify_user_sync,
        query_log         : Any                      = None,
        auto_debug        : bool                     = False,
        inject_bugs       : bool                     = False,
        similarity_floor  : float                    = 100.0,
        writeback_enabled : bool                     = False,
        receptionist_factory : Callable[ ..., Any ]  = ReceptionistAgent,
        notifier          : Callable[ [ Any ], Any ] = notify_user_async,
        agentic_factory   : Optional[ Callable[ ..., Any ] ] = None,
    scope_registry_fn : Optional[ Callable[ [ ], dict ] ] = None,
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
        # The near-match branch (step 6b). `confirmation_threshold` None means the branch
        # does not exist for this flow — no ask and no auto-accept, so a caller that
        # forgets to wire it gets v2's behaviour up to now (route below a perfect hit)
        # rather than a new replay nobody asked for. Failing closed is the only safe
        # direction for a guard whose job is to decide whether to serve a near answer.
        self.confirmation_threshold = confirmation_threshold
        self.confirmation_enabled   = confirmation_enabled
        self.confirmer              = confirmer
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
        # HOW THE DOOR LEARNS WHICH FILES A source_document MAY NAME. A CALLABLE, not the
        # registry itself: the real one is built at FastAPI startup from the INI, so
        # holding the dict here would freeze whatever existed when this flow was
        # constructed and would drag a booted application into every test of this class.
        # None means the check is unwired — the argument is then refused rather than
        # waved through, because a scope check that silently does not run is worse than
        # no feature at all. See _refuse_bad_source_documents.
        self.scope_registry_fn    = scope_registry_fn
        self.notifier             = notifier
        self.trace_dir            = trace_dir
        self.debug                = debug
        self.verbose              = verbose

    # ---------------------------------------------------------------- the flow
    def ask(
        self, question: str, user_id: str, user_email: str, session_id: str, websocket_id: str,
        speak: bool=True, interactive: bool=True, parent_id_hash: Optional[ str ]=None,
    ) -> dict:
        """Route one question through router, cache, arguments and executor.

        This is the only path that may reach needs-input, because it is the one with a human waiting at the other end.

        parent_id_hash names the monopolize job this ask was made for. It rides the per-request trace to the
        queued executor. The executor stamps it on the job as spawned_by_id_hash, so the consumer admits the job through a monopoly hold.
        It travels on the trace, not in ctx, because ctx is unpacked in many places. Absent (None or empty), nothing is recorded.
        """
        trace = StageTrace( trace_dir=self.trace_dir )
        trace.mark( "t_recv" )
        if parent_id_hash: trace.set( "parent_id_hash", parent_id_hash )
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
            # THE SECOND READER, on the door a person actually talks to. `resolve()` is
            # scoped to the conversational class (registry §5.1.3), so every agentic
            # command lands here — and this used to answer the receptionist's "I do not
            # understand" to a command the registry knows. Since the spoken door hands
            # its transcription to `ask`, that made "do a deep research on the state of
            # AI" unanswerable by voice. `submit` learned this first; the voice path had
            # the identical gap and nothing was asking about it.
            agentic = resolve_agentic( command )
            if agentic is not None:
                return self._ask_agentic( trace, agentic, command, raw_args, question, ctx, interactive )
            return self._receptionist( trace, question, ctx,
                                       self._unresolved_route_reason( command ),
                                       routed_command=self._unresolved_routed_command( command ) )

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
            # STEP 9b, AT THE REPLAY DECISION — deliberately here and not inside the
            # lookup. A guard in the shared search helper would also filter
            # /api/admin/snapshots/search, blinding the one person whose job is to
            # inspect the cache, and doing it silently. The question this asks is "may
            # this row be SERVED as an answer", and only the replay path asks it.
            # Refusing here falls through to routing, so the agent re-runs — which is
            # the whole observable behaviour, not a detail of it.
            if lookup.is_replay_hit and self._may_serve( trace, lookup.snapshot, "exact_hit" ):
                # WHICH ROW WE ARE ABOUT TO REPLAY, captured HERE and not taken off the
                # outcome (row 7e2125a7, D7). The executor binds the same value inside its
                # own try, one line after a call that can raise, so on the earliest failure
                # it has no id to report — and the failure Outcome is discarded at the
                # degrade boundary below anyway. Reading it from the row we already hold
                # cannot be skipped by any failure inside the replay.
                replayed_id = lookup.snapshot.id_hash
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
                                         agent_label=spec.label, replayed_snapshot_id=replayed_id )
                # primary_error, like the agent path at the bottom of _run_agent. Without
                # it the receptionist's own (absent) error is all that is emitted, so a
                # replay that died of "Cannot execute empty code list" reached the client
                # as error=null — 115 of 117 failures in the 2026-08-21 warm pass could
                # not say why (bug 38815328).
                return self._receptionist( trace, question, ctx, "replay_error",
                                           primary_error=outcome.error,
                                           replayed_snapshot_id=replayed_id,
                                           routed_command=command )

            # 2b — the NEAR match. Above the confirmation threshold but short of exact,
            # so the flow asks the user the question the voice path asks today and
            # replays only on a yes. Rick ruled on 2026-08-20 that the brain gets the ask.
            #
            # Without it, 7b would delete the queue's copy and leave running_fifo_queue's
            # accept-above-the-floor — which is safe ONLY because the upstream ask
            # happened — and a 90-to-99% match would replay an answer nobody confirmed.
            near_match, near_reason = self._near_match_replay( trace, lookup, ctx, interactive, question )
            if near_match is not None:
                replayed_id = near_match.id_hash          # same reason as the exact-hit site above
                work    = Work( "replay", near_match, user_id, user_email, session_id, snapshotable=False )
                outcome = self.executor.submit( work, trace )
                if outcome.status in SUCCESS_STATUSES:
                    return self._finish( trace, "replay", near_reason, outcome, question, ctx,
                                         command=command, cache_hit=True, agent_label=spec.label,
                                         replayed_snapshot_id=replayed_id )
                return self._receptionist( trace, question, ctx, "replay_error",
                                           primary_error=outcome.error,
                                           replayed_snapshot_id=replayed_id,
                                           routed_command=command )

        # 3 — arguments.
        if not spec.required_args:
            return self._run_agent( trace, spec, command, question, {}, ctx, "args_none" )
        arg_spec = self._arg_spec_for( command, spec.required_args )
        trace.mark( "t_extract" )
        try:
            extraction = self.expeditor.extract( command, raw_args, question, arg_spec )
        except Exception as e:
            trace.set( "extract_error", str( e ) )
            return self._receptionist( trace, question, ctx, "extract_error",
                                       routed_command=command )
        trace.update( args_known=sorted( extraction.final_args.keys() ), args_missing=list( extraction.missing ) )
        if extraction.missing:
            return self._needs_input( trace, command, extraction, question, ctx, interactive )
        return self._run_agent( trace, spec, command, question, extraction.final_args, ctx, "args_complete" )

    # ---------------------------------------------------------------- the other door
    def submit(
        self, user_id: str, user_email: str, session_id: str, websocket_id: str,
        command: Optional[ str ]=None, args: Optional[ dict ]=None, question: Optional[ str ]=None,
        job: Any=None, speak: bool=True,
        scheduled_at: Optional[ str ]=None, monopolize: bool=False,
        parent_id_hash: Optional[ str ]=None,
    ) -> dict:
        """Run work whose command is already decided: the door beside ask.

        It skips cache lookup, routing and argument extraction, because the caller already named the command or built the job. It then joins the path ask shares: build, run, guarded write-back, notify.
        A new named job arrives as command plus args. A saved job being continued arrives as job, an object the in-process caller already holds. Taking the built job spares that caller describing it in a command string, which would be a lossy round trip with no gain.
        It never parks. A submit caller is usually a service that would never read a parked question. Missing arguments come back as status needs_input with args_missing filled in. Only ask may reach needs-input.
        The queue directives scheduled_at, monopolize and parent_id_hash are not agent arguments. args cannot carry them, because args is checked against the command's argument contract. They reach the job through the factory and mean something only on the agentic path.
        Requires:
            - exactly one of (`command`, `job`) is supplied.
            - when `command` is supplied it resolves in the registry, and `args` carries
              every one of that command's required arguments.

        Ensures:
            - returns the same terminal dict shape `ask` returns; never raises for a
              routing or agent failure.
            - `status="waiting"` is a success, not a degrade. A queued executor returning
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
        # ONE definition of "there is a question here", used by all three sites below:
        # what gets logged as the verbatim, whether the row says those words are a
        # person's, and whether the result may be cached. `ask`'s fitness gate already
        # says a blank-or-whitespace question is no question; `submit` has no gate, so
        # it borrows the same rule rather than growing a second, looser one.
        has_question = self._has_question( question )
        trace.update( decision_floor=self.similarity_floor, speak=speak, interactive=False, entry="submit",
                      question=question if has_question else ( command or "" ) )
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
        if not has_question:
            trace.set( "verbatim_source", "command" if command is not None else "job" )
        ctx = ( user_id, user_email, session_id, websocket_id, speak )

        # WHEN A QUEUE DIRECTIVE HAS NOWHERE TO GO, SAY SO IN THE TRACE. Only the
        # agentic path builds a job this method can stamp. A caller handing over a job
        # it built itself has already set whatever it wanted on that object, and a
        # conversational command runs inline on this thread, where "run it at ten in the
        # morning" has no meaning at all. Neither case is worth refusing the work over —
        # but silently dropping a `scheduled_at` would let a job the caller believes is
        # deferred run immediately with nothing anywhere saying why.
        directives = { "scheduled_at": scheduled_at, "monopolize": monopolize,
                       "parent_id_hash": parent_id_hash }
        directives_set = sorted( k for k, v in directives.items() if v )

        # A job handed over whole: the caller built it, so there is nothing to resolve.
        if job is not None:
            if directives_set: trace.set( "queue_directives_ignored", ",".join( directives_set ) )
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
                return self._submit_agentic( trace, agentic, command, dict( args or {} ), question, ctx,
                                             scheduled_at, monopolize, parent_id_hash )
            route_reason = self._unresolved_route_reason( command )
            if route_reason == "unknown_command": trace.set( "unknown_command", command )
            return self._receptionist( trace, question or command, ctx, route_reason,
                                       routed_command=self._unresolved_routed_command( command ) )

        if directives_set: trace.set( "queue_directives_ignored", ",".join( directives_set ) )

        final_args = dict( args or {} )
        missing    = [ arg for arg in spec.required_args if not final_args.get( arg ) ]
        if missing:
            return self._submit_needs_input( trace, command, missing, sorted( final_args ), ctx )

        # THE CACHE NARROWING THAT USED TO LIVE HERE IS NOW STEP 9a's, AND ONLY 9a's.
        # It read `snapshotable=spec.snapshotable and has_question`, because a
        # question-less submit would file a row under the command string — "agent router
        # go to math" — which no user will ever say, so the row could never be hit and
        # only cost a read on every lookup (Pocholo, reviewing step 10). 9a refuses the
        # write for EVERY submit, question or not: the caller named the command, so the
        # row would assert on nobody's authority but theirs. Keeping both would leave two
        # places deciding one thing, which is the shape this plan has already been bitten
        # by. `has_question` still governs what gets LOGGED and how the row is typed,
        # above — that half is live and separately pinned.
        #
        # ⚠️ If `submit` ever regains write-back for some narrower case, the no-question
        # narrowing has to come back WITH it. It is not obsolete; it is subsumed.
        return self._run_agent( trace, spec, command, question if has_question else command,
                                final_args, ctx, "submitted" )

    # ------------------------------------------------------- the agentic arm of ask
    @staticmethod
    def _split_queue_directives( args: dict ) -> tuple:
        """
        Pull the two runtime scheduling arguments out of a set the expeditor produced.

        The expeditor offers scheduled_at and monopolize as universal runtime arguments for every agentic command. So a spoken "run the deep research at ten tomorrow" comes back as ordinary argument keys.
        They are not agent arguments. create_agentic_job reads its arguments by name and does not name them. Left in place, they are dropped silently and the job runs at once.
        The v1 queue removed them at this point and set them on the job afterwards. The normalisation below is v1's too, kept word for word so "immediately" keeps its meaning for the user.

        Requires:
            - args is the argument dict the expeditor returned

        Ensures:
            - returns ( args_without_them, scheduled_at, monopolize )
            - the input dict is not mutated, since the caller may still want it whole
            - "immediately" / "now" / "none" mean no schedule, not a date string
            - "yes" / "true" / "1" mean monopolize; any other string does not
        """
        remaining    = { k: v for k, v in args.items() if k not in ( "scheduled_at", "monopolize" ) }
        scheduled_at = args.get( "scheduled_at" )
        monopolize   = args.get( "monopolize" )

        if scheduled_at and str( scheduled_at ).lower() in ( "immediately", "now", "none" ):
            scheduled_at = None

        if isinstance( monopolize, str ):
            monopolize = monopolize.lower() in ( "yes", "true", "1" )
        else:
            monopolize = bool( monopolize ) if monopolize else False

        return remaining, scheduled_at, monopolize

    def _ask_agentic(
        self, trace: StageTrace, spec: Any, command: str, raw_args: Any,
        question: str, ctx: tuple, interactive: bool,
    ) -> dict:
        """Run an agentic command the router chose, extracting its arguments from prose.

        resolve() covers only the conversational class and returns None for every agentic command. This arm is the second reader that makes agentic commands work on the voice door.
        Unlike submit, it extracts and parks. The human who spoke is still there, so a missing argument goes through the interview and is parked for resume.
        It skips the cache, because an agentic job is long-running work with a job id, not a reusable answer. It returns before the lookup.

        Requires:
            - spec is an agentic AgentSpec from resolve_agentic( command )
            - question is the human's words; raw_args is whatever the router pulled out

        Ensures:
            - complete arguments build the job and run it through the same path a
              submitted agentic job takes, so there is one spelling of "build this and
              run it", not two
            - a missing argument parks and asks when interactive, and returns the
              question without parking when not
            - an extraction failure degrades to the receptionist rather than raising
        """
        arg_spec = self._arg_spec_for( command, spec.required_args )
        trace.mark( "t_extract" )
        try:
            extraction = self.expeditor.extract( command, raw_args, question, arg_spec )
        except Exception as e:
            trace.set( "extract_error", str( e ) )
            return self._receptionist( trace, question, ctx, "extract_error",
                                       routed_command=command )

        trace.update( args_known=sorted( extraction.final_args.keys() ),
                      args_missing=list( extraction.missing ) )
        if extraction.missing:
            return self._needs_input( trace, command, extraction, question, ctx, interactive )

        args, scheduled_at, monopolize = self._split_queue_directives( extraction.final_args )
        return self._submit_agentic( trace, spec, command, args, question, ctx,
                                     scheduled_at, monopolize, None )

    def _submit_agentic(
        self, trace: StageTrace, spec: Any, command: str, args: dict,
        question: Optional[ str ], ctx: tuple,
        scheduled_at: Optional[ str ]=None, monopolize: bool=False,
        parent_id_hash: Optional[ str ]=None,
    ) -> dict:
        """Build an agentic job from ( command, args ) and run it like any other submit.

        This is what every submit endpoint did in its own handler: check the declared arguments, call create_agentic_job, queue the result. Doing it here lets those doors retire into one.
        The argument check comes from spec.required_args, the same JOB_ARG_CONTRACTS entry the expeditor reads. A job that gains a required argument gains it here with no edit.
        The factory also receives scheduled_at and monopolize. parent_id_hash becomes the job's spawned_by_id_hash. That lets the queue consumer admit a monopolizing sweep's own children through the hold. A door that dropped it would leave those children deferred with nothing to show why.

        Requires:
            - spec is an agentic AgentSpec from resolve_agentic( command )

        Ensures:
            - missing arguments return the same non-parking needs_input refusal a
              conversational submit returns; nothing is built and nothing is queued
            - a factory that cannot build the command degrades to the receptionist
              rather than raising out of the door
            - a built job runs through the same path as a job handed over whole, so
              there is one spelling of "run this and report it", not two
        """
        refusal = self._refuse_bad_source_documents( trace, command, args, ctx )
        if refusal is not None: return refusal

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
                command            = command,
                args_dict          = args,
                user_id            = user_id,
                user_email         = user_email,
                session_id         = session_id,
                debug              = self.debug,
                verbose            = self.verbose,
                scheduled_at       = scheduled_at,
                monopolize         = monopolize,
                spawned_by_id_hash = parent_id_hash,
            )
        except SubmitRefused as refused:
            # A builder with a specific reportable reason to decline (the mock-job expeditor
            # test's cancelled interview): a terminal `failed` carrying that reason and the
            # builder's details, NOT the generic degrade below, which would lose both.
            trace.set( "submit_refused", refused.route_reason )
            return self._emit(
                trace, path="agent", status="failed", route_reason=refused.route_reason,
                answer=None, answer_raw=None, command=command, ctx=ctx,
                error=refused.message, submit_details=refused.details,
            )
        except Exception as e:
            trace.set( "agentic_build_error", str( e ) )
            return self._receptionist( trace, question or command, ctx, "agentic_build_error",
                                       primary_error=str( e ), routed_command=command )
        if job is None:
            # The factory returns None for a command it does not know. The registry said
            # it was agentic, so the two tables disagree — say which command, because a
            # bare receptionist here would send the next reader hunting.
            trace.set( "agentic_build_error", f"factory returned None for {command}" )
            return self._receptionist( trace, question or command, ctx, "agentic_build_error",
                                       primary_error=f"factory returned None for {command}",
                                       routed_command=command )

        result = self._submit_prebuilt( trace, job, question or command, ctx )
        # WHAT THE BUILDER LEARNED ABOUT THE JOB IT BUILT rides back on the result. Only a
        # dict counts: `submit_details` is an optional attribute a builder may set (the
        # mock-job command sets its resolved config), and a job without one has nothing to
        # report.
        details = job.submit_details if hasattr( job, "submit_details" ) else None
        if isinstance( details, dict ) and result[ "path" ] == "agent":
            result[ "submit_details" ] = details
        return result

    def _submit_prebuilt( self, trace: StageTrace, job: Any, question: str, ctx: tuple ) -> dict:
        """Run a job the caller already built, with no registry lookup and no argument work.

        snapshotable is False because a caller handing over a constructed job has not said the result is a reusable answer. Writing one back on a guess would put rows in the cache that ask would later replay.
        """
        work    = Work( "agent", job, ctx[ 0 ], ctx[ 1 ], ctx[ 2 ], snapshotable=False )
        outcome = self.executor.submit( work, trace )
        # ONE spelling of the outcome test across this file, not three. This used to read
        # `== "failed"`, which is the same idea said a third way and drifts the first time
        # a new non-success status appears — it would fall through as a success here while
        # both gates above refused it.
        if outcome.status not in SUCCESS_STATUSES:
            # `job.routing_command`, NOT `command` — there is no `command` in this scope, and
            # my first pass wrote one here and raised NameError on the degrade path. Caught
            # by test_a_prebuilt_job_that_fails_degrades_to_the_receptionist, which is the
            # same failure D7's ratified form would have had: a record-improving change that
            # crashes the exact path it was meant to make readable. The success exit two
            # lines below already reads `job.routing_command`; the degrade now agrees with it.
            return self._receptionist( trace, question, ctx, "agent_error",
                                       primary_error=outcome.error,
                                       routed_command=job.routing_command )
        # `routing_command` is REQUIRED by the QueueableJob protocol (queue_protocol.py:61),
        # so read it. It used to be a getattr with an "" fallback, which would have turned a
        # job that violates the protocol into a row with a blank command — silently, and into
        # exactly the nullable blank-defaulted column this plan condemns elsewhere.
        return self._finish( trace, "agent", "submitted_prebuilt", outcome, question, ctx,
                             command=job.routing_command )

    def _submit_needs_input( self, trace: StageTrace, command: str, missing: list,
                             known: list, ctx: tuple ) -> dict:
        """Refuse an under-specified submit without parking it.

        The ask path stores a pending entry and asks the human the first question. Doing that here would park a question at a service account. The entry would sit until it expired, and the caller would get a pending_id it cannot answer.
        So this returns the same shape minus the park: no pending_id, nothing stored, status="needs_input".
        """
        trace.mark( "t_first_useful" )
        trace.update( args_missing=missing, args_known=known )
        return self._emit( trace, path="needs_input", status="needs_input",
                           route_reason="args_incomplete_no_park", answer=None, answer_raw=None,
                           command=command, ctx=ctx, pending_id=None,
                           args_missing=missing, args_known=known )

    def _refuse_bad_source_documents( self, trace: StageTrace, command: str, args: dict, ctx: tuple ) -> Optional[ dict ]:
        """Validate `source_document` at the door, or return the refusal that stops the submit.

        An unresolvable, out-of-scope or missing source document is refused before the job is created, not inside the agent after it starts. A job already accepted that cannot read its own input fails somewhere far less visible. This runs on the door's thread and its refusal is the door's answer.
        It mutates args on success. The caller names a document the way the doc-viewer does, as `<scope>/<path>`, and the agent needs a real absolute path. Resolving once here means the agent never re-derives it differently from what was validated.
        The unwired case refuses. With no scope registry injected this cannot tell an allowed path from any other. A scope check that silently does not run would let the argument through unvalidated, which means arbitrary file read.

        Requires:
            - args is the mutable dict of arguments this submit will run with

        Ensures:
            - returns None when there is nothing to refuse, including when the argument
              is absent, which is legal because it is optional
            - returns a terminal refusal dict when the argument is present and bad, or
              when a near-miss spelling of it is present (see _near_miss_source_document_key)
            - on success replaces args[ SOURCE_DOCUMENT_ARG ] with the list of resolved,
              real, absolute paths
            - never raises

        Raises:
            - None. The door answers with a refusal, not a stack trace
        """
        near_miss = self._near_miss_source_document_key( args )
        if near_miss is not None:
            trace.set( "source_document_near_miss", near_miss )
            return self._submit_refused(
                trace, command, ctx, "source_document_unknown_key",
                f"'{near_miss}' is not an argument this command takes. Did you mean "
                f"'{SOURCE_DOCUMENT_ARG}'? Nothing was run — a misspelled argument would "
                f"otherwise be accepted in silence and the research would read nothing."
            )

        if SOURCE_DOCUMENT_ARG not in args: return None
        raw = args.get( SOURCE_DOCUMENT_ARG )
        if raw is None or raw == "" or raw == [ ]: return None

        if self.scope_registry_fn is None:
            return self._submit_refused(
                trace, command, ctx, "source_document_unwired",
                f"'{SOURCE_DOCUMENT_ARG}' cannot be validated: no document scopes are "
                f"configured on this server, so no path can be shown to be readable."
            )

        paths, error = validate_source_documents( raw, self.scope_registry_fn() )
        if error is not None:
            trace.set( "source_document_refused", error )
            return self._submit_refused( trace, command, ctx, "source_document_invalid", error )

        args[ SOURCE_DOCUMENT_ARG ] = paths
        trace.set( "source_document_count", len( paths ) )
        return None

    @staticmethod
    def _near_miss_source_document_key( args: dict ) -> Optional[ str ]:
        """Return an argument key that was probably meant to be `source_document`.

        /api/v2/submit binds args as a free-form dict, so a key no command declares is accepted without comment. A misspelled source_document would run the job and the research would read nothing, with no error anywhere and a report that looks like any other.
        The check is narrow by scope. Rejecting every unrecognised key on every command would change behaviour for any caller that passes an extra key today, and needs its own blast-radius review. This catches the one shape being introduced.

        Requires:
            - args is the caller's argument dict

        Ensures:
            - returns None when no key resembles the canonical spelling, or when the
              canonical spelling itself is present (an exact key is never a near miss)
            - returns the offending key when one normalizes to the canonical form or is
              within a close-match cutoff of it
            - never raises
        """
        if SOURCE_DOCUMENT_ARG in args: return None

        canonical = SOURCE_DOCUMENT_ARG.replace( "_", "" )
        for key in args.keys():
            if not isinstance( key, str ): continue
            normalized = key.lower().replace( "_", "" ).replace( "-", "" ).replace( " ", "" )
            if normalized == canonical: return key
            if difflib.get_close_matches( normalized, [ canonical ], n=1, cutoff=0.85 ): return key
        return None

    def _submit_refused( self, trace: StageTrace, command: str, ctx: tuple,
                         route_reason: str, message: str ) -> dict:
        """Emit a door-level refusal: the submit shape for "no, and here is why".

        It has the same shape as _submit_needs_input but a different meaning. needs_input means the caller left something out and can supply it. This means what the caller supplied cannot be used.
        Collapsing them would make a bad path read as a missing argument, and the caller would retry the same bad path forever.

        Ensures:
            - nothing is built and nothing is queued
            - the refusal text reaches the caller as the answer, so it is readable in the
              same response rather than only in a log
        """
        trace.mark( "t_first_useful" )
        return self._emit( trace, path="needs_input", status="needs_input",
                           route_reason=route_reason, answer=message, answer_raw=message,
                           command=command, ctx=ctx, pending_id=None,
                           args_missing=[ ], args_known=[ ] )

    # ---------------------------------------------------------------- the second turn
    def resume( self, pending_id: str, answer: str, websocket_id: str, speak: bool=True ) -> dict:
        """Fold a human's answer into a parked request and drive it to a terminal result.

        It runs on the caller's thread and spawns no background thread of its own. The park site stores a continuation. This second turn runs it to completion rather than handing it to a worker and returning early.
        The router in routers/v2_ask.py awaits it through run_in_threadpool, so it executes on a worker thread, not on the event loop.
        It claims the whole turn atomically. A second resume of a completed conversation would otherwise index an empty missing list, and two concurrent resumes would put answers in the wrong slots. Both are refused as already_resumed.

        Requires:
            - pending_id identifies a parked entry; answer is the human's reply to
              that entry's first missing argument.

        Ensures:
            - a missing or expired pending_id refuses loudly (status='expired',
              route_reason='pending_expired'), never a 500, never a silent no-op.
            - the answer fills the first missing arg; if more remain, the same
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
            # The park that led here was made by the agentic arm of `ask`, so the command
            # is agentic and this lookup was always going to miss. Without the fallback a
            # user answers the one question the interview asked and is told the command
            # is not understood — after it was understood well enough to ask.
            agentic = resolve_agentic( entry.command )
            if agentic is None:
                self.pending.set_status( pending_id, "failed", error="unknown_command" )
                return self._receptionist( trace, entry.question, ctx, "unknown_command" )
            args, scheduled_at, monopolize = self._split_queue_directives( extraction.final_args )
            result = self._submit_agentic( trace, agentic, entry.command, args, entry.question, ctx,
                                           scheduled_at, monopolize, None )
            self.pending.set_status( pending_id, result[ "status" ],
                                     answer=result.get( "answer" ), error=result.get( "error" ) )
            return result
        result = self._run_agent( trace, spec, entry.command, entry.question, extraction.final_args, ctx, "resumed" )
        self.pending.set_status( pending_id, result[ "status" ], answer=result.get( "answer" ), error=result.get( "error" ) )
        return result

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _has_question( question: Optional[ str ] ) -> bool:
        """Say whether question is a question at all, by the rule _unfit_reason uses.

        Blank, absent and whitespace-only all mean no question, and they must mean it in one place. The three sites in submit that ask this would otherwise drift apart. A looser one is how a routing command gets logged as a person's words, or cached under a key nobody will ever say.
        """
        return bool( question and question.strip() )

    @staticmethod
    def _unfit_reason( question: str ):
        """
        Why this question is refused, or None if it is fit to process.

        The three rules and their wording are v1's, kept verbatim so a user hears the same refusal after the switch.
        It returns the spoken reason and a route_reason, so the trace records which rule fired rather than a flat "rejected".
        """
        if not AskFlow._has_question( question ):
            return ( REJECTION_EMPTY, "empty_question" )
        if len( question ) > MAX_QUESTION_CHARS:
            return ( REJECTION_TOO_LONG, "question_too_long" )
        if question.lower().startswith( "invalid" ):
            return ( REJECTION_INVALID, "invalid_content" )
        return None

    def _log_query( self, trace: StageTrace, ctx: tuple, snapshot_id, cache_hit: bool ) -> None:
        """
        Write this request to the query log, v1's _log_query_with_results.

        The flow writes it, so the query log keeps growing for voice traffic. It has one call site, at the terminal chokepoint. Every exit funnels through _emit, so a refusal, a needs-input park and an answered question are all logged.
        A logging failure never breaks a request. It is swallowed with a debug print, because a question must not fail over an analytics row.
        Two fields are left out, rather than filled with something that would read as fact:
          - embeddings: CacheLookup does not return the vectors, and v2 skips embedding on a tier-1 exact hit. Generating them to log them would re-add the cost v2 avoids.
          - cache_hits: v1's flags mean an embedding was generated and came back non-empty, which is not what v2's embed_cached reports. One fact under the other's column name is a quiet wrongness.
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

    def _near_match_replay( self, trace: StageTrace, lookup: Any, ctx: tuple, interactive: bool, question: str ) -> tuple:
        """Decide whether a below-exact candidate may be replayed, and under what reason.

        Returns ( snapshot, route_reason ) to replay, or ( None, None ) to route on. There are three branches, as in v1:
          - the score is out of range, below 0 or above 100: refuse the measurement and route. A replay used to need a tier-1 exact hit, so no float ever decided one. The gist tier and this branch reopen that door, so the guard lives here.
          - confirmation on: ask "Is that the same as: ...?" and replay only on a yes. Anything else, a timeout included, routes. The prompt defaults to no, because a wrong replay is a confident answer to a question nobody asked.
          - confirmation off (the INI key `similarity confirmation enabled` set to false): auto-accept with no prompt, as v1 does. Each branch names itself in the emitted route_reason.
        Before any ask it also routes on a candidate that names a different quantity (near_match_guard). It routes on a row _may_serve will not serve too, since the answer cannot change the outcome.
        A non-interactive caller is declined without being asked, because an unattended caller cannot consent.
        The ask blocks this thread for the whole retry ladder, as v1's does. That is affordable because the handler runs off the event loop through run_in_threadpool. It is not affordable when nobody is listening, which is what `interactive` decides.
        """
        if self.confirmation_threshold is None:
            return ( None, None )
        candidate = lookup.best_candidate
        score     = lookup.best_score
        if candidate is None or score is None:
            return ( None, None )
        if score < 0 or score > 100:
            trace.set( "similarity_out_of_range", score )
            if self.debug: print( f"[v2] refusing a similarity of {score} — out of range; routing" )
            return ( None, None )
        if score < self.confirmation_threshold:
            return ( None, None )

        # ROW 1b3ec88f — A NEAR MATCH MUST NOT CHANGE THE QUANTITY ASKED ABOUT. Measured on :8000
        # (job ts-8278f1c5): "Convert 10 miles to kilometers" replayed the stored answer of "How many
        # miles is 10 kilometers?" at a score of 93.4, because a similarity score reads two questions
        # that differ only in which unit the 10 belongs to as nearly identical. The check is on the
        # ORDERED numbers and the word after each (near_match_guard), and it runs BEFORE the ask and
        # before 9b: a user asked "is that the same?" about a different quantity is asked a question
        # whose honest answer is no, and the answer is wrong whether or not anyone is asked.
        if quantities_differ( question, candidate.question ):
            trace.set( "near_match_refused_quantity", score )
            if self.debug: print( f"[v2] near match at {score:.1f}% names a different quantity — routing" )
            return ( None, None )

        # STEP 9b, ON THIS PATH TOO, AND BEFORE THE ASK. An unconfirmed row is not served
        # even if the user says yes — so asking about one would put a question to somebody
        # whose answer cannot change the outcome. Checking first also keeps the two replay
        # paths honest with each other: "never served, not even once" would be false if a
        # near match could carry a row past the guard the exact path applies.
        if not self._may_serve( trace, candidate, "near_match" ):
            if self.debug: print( f"[v2] near match at {score:.1f}% is unconfirmed — not asking, routing" )
            return ( None, None )

        if not self.confirmation_enabled:
            trace.set( "near_match_auto_accepted", score )
            return ( candidate, "near_match_auto_accepted" )

        # NOBODY IS THERE TO ASK ⇒ DO NOT ASK (Pocholo, on 1b7310ce). `interactive=False`
        # says the caller is a service account or a watchdog — dead_queue_watchdog's retry
        # is one — so the prompt would go to a user who never sees it, hold this thread
        # through the whole 30/60/120s retry ladder, and then default to "no" anyway. The
        # answer is the same; the wait is not.
        #
        # It DECLINES rather than accepts: an unattended caller cannot consent, and
        # `interactive` says whether a human can answer, not whether the match is good.
        # Confirmation being OFF is a different statement — that nobody should be asked at
        # all — which is why the auto-accept above is untouched by this.
        if not interactive:
            trace.set( "near_match_declined_non_interactive", score )
            if self.debug: print( f"[v2] near match at {score:.1f}% declined unasked — no human on this call" )
            return ( None, None )

        if self._user_confirms( candidate, score, ctx ):
            trace.set( "near_match_confirmed", score )
            return ( candidate, "near_match_confirmed" )
        trace.set( "near_match_declined", score )
        return ( None, None )

    def _user_confirms( self, candidate: Any, score: float, ctx: tuple ) -> bool:
        """Ask the user whether the near match is the same question. Yes, or route.

        The request is the queue's, field for field. A confirmer that raises counts as a no: a broken notification path is not evidence that two questions are the same. A replay served because the ask broke is the wrong-but-close answer this branch exists to prevent.
        """
        _user_id, user_email, _session_id, _websocket_id, _speak = ctx
        request = NotificationRequest(
            message          = CONFIRMATION_QUESTION.format( question=candidate.question ),
            response_type    = ResponseType.YES_NO,
            response_default = "no",
            timeout_seconds  = 30,
            priority         = "high",
            suppress_ding    = True,
            target_user      = user_email,
            # The same sender the flow already speaks as (_speak, below). The field is
            # pattern-validated: lowercase dot-separated words only, so "v2.ask" is
            # rejected at the model — a made-up id passes only until something speaks.
            sender_id        = "ask.flow@lupin.deepily.ai",
        )
        try:
            response = self.confirmer( request, retry_on_timeout=True, max_attempts=3,
                                       backoff_multiplier=2.0 )
        except Exception as e:
            if self.debug: print( f"[v2] near-match confirmation failed ({e}) — treating as no" )
            return False
        confirmed = response.status == "responded" and response.response_value == "yes"
        if self.debug: print( f"[v2] near match at {score:.1f}%: user said {response.status}:{response.response_value}" )
        return confirmed

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
        """Construct an agent the way the queue constructs one.

        question is the user's original text; agent_question is that text with the expeditor's extracted values folded in. Both are needed: the gist and the salutation are read off the original, while the agent is asked the composed one.
        Five kwargs match push_job: question_gist, debug, verbose, auto_debug, inject_bugs. Three differ from v1, each by a ruling:
          - question: the flow passes the composed question. v1 never ran the expeditor for conversational commands, so the agent re-parsed the raw text. Passing the raw question here would drop the extracted arguments.
          - last_question_asked: the flow passes the intended form, salutation plus the stripped question. v1 builds salutations + " " + question from the original, which still holds the salutation, so "hey what is the weather" would reach every agent as "hey hey what is the weather".
          - push_counter: v1's counter lives on the queue singleton, which the flow cannot see without reading through the executor into its queue. That coupling is what the executor seam prevents, and the inline executor has no queue. It stays -1.
        debug=True and verbose=False are v1's literals, not the flow's own flags. push_job hardcodes them and ignores the queue's. An agent keeps the debug output it had under v1.
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
        """Fold extracted arg values into the question so the agent re-parses them.
        """
        composed = question
        for value in final_args.values():
            if value and str( value ).lower() not in composed.lower():
                composed = f"{composed} {value}"
        return composed

    def _run_agent(
        self, trace: StageTrace, spec: Any, command: str, question: str, final_args: dict,
        ctx: tuple, route_reason: str, snapshotable: Optional[ bool ]=None,
    ) -> dict:
        """Build and run a pre-existing agent; degrade to the receptionist on failure.

        snapshotable defaults to the registry's answer for this command. A caller passes it only to say no more strongly than the registry does. No caller does today. submit does not. Without a question it has no sensible row to file under, and the write guard already refuses every submit. The has_question test in submit now decides only what is logged and which text the agent receives.
        The write guard also refuses the write for any route_reason the router did not choose, which is how submit stays out of the cache.
        """
        may_cache      = spec.snapshotable if snapshotable is None else snapshotable
        may_cache      = self._write_guard( trace, spec, route_reason, may_cache )
        agent_question = self._compose_question( question, final_args )
        work           = Work( "agent", self._build_agent( spec.factory, agent_question, ctx, question ),
                               ctx[ 0 ], ctx[ 1 ], ctx[ 2 ], snapshotable=may_cache )
        outcome        = self.executor.submit( work, trace )
        # GATE 2 of 2. Same reason as gate 1, on the ordinary path: narrow this back
        # to `!= "done"` and EVERY queued job degrades to the receptionist the moment
        # it is handed off, while the real agent still runs behind it.
        if outcome.status not in SUCCESS_STATUSES:
            return self._receptionist( trace, question, ctx, "agent_error",
                                       primary_error=outcome.error, routed_command=command )
        return self._finish( trace, "agent", route_reason, outcome, question, ctx,
                             command=command, snapshotable=may_cache,
                             agent_class_name=spec.factory.__name__, agent_label=spec.label )

    @classmethod
    def _may_serve( cls, trace: StageTrace, snapshot: Any, why: str ) -> bool:
        """Decide whether a cached row may be served as an answer: the read guard.

        Only a row confirmed correct is served. answer_is_correct must be True; None (never answered) and False (the user said no) both refuse.
        The one exemption is an exact hit (why="exact_hit") whose verdict is not False. It is the same question whose answer this user already received, so re-running it gives the same answer later and at cost. An exact hit the user marked wrong is still refused.
        Near matches and the fallback after a failed re-execution stay guarded, because the row served there is not the question that was asked.
        The exemption is keyed on why, not on a score, so a 99.9 never counts as close enough. The test is is True, not truthiness, so the string "true" or the number 1 is not read as consent.
        Read the hydrated object, never the raw column: the record builder makes the object uniform and the column is not. A missing attribute means refuse.
        The only verdict ever asked of the user is the end-of-execution "was this answer correct?". It lands on a daemon thread, so a timeout leaves it None. This guard only consumes it and adds no prompt.
        A refused row is marked in the trace, so "guard refused it" can be told from "cache is broken".
        """
        # AN EXACT MATCH IS EXEMPT (Rick, 2026-09-04, row fe1c0d3f). A tier-1 hit is the
        # SAME question, verbatim or normalized, whose answer this user already received.
        # Re-running it cannot produce a better answer — it produces the same answer, later
        # and at cost. v1 behaved this way and never had a gate here at all
        # (todo_fifo_queue.py: `elif best_score >= 100.0: auto-accept, no prompt`); this
        # reproduces that BEHAVIOUR inside v2's own path, and does not revive v1's code.
        #
        # WHY THE EXEMPTION IS KEYED ON `why` AND NOT ON A SCORE. Every call site already
        # names itself, and the name is the thing being ruled on: "exact_hit" is exempt,
        # "near_match" and "failed_reexecution_fallback" are NOT. Threading a similarity
        # float down here instead would let a 99.9 arrive as "close enough" — the float
        # comparison R-C1 exists to forbid.
        #
        # 🔴 WHAT THIS DELIBERATELY DOES NOT WEAKEN. The guard still stands on every path
        # where the served row is NOT the question that was asked: a near match is a
        # DIFFERENT question, and the fallback after a failed re-execution is a safety net
        # where an unconfirmed answer is most likely to be the wrong one. Rick ruled both
        # of those stay guarded in the same breath as this exemption.
        verdict = getattr( snapshot, "answer_is_correct", None )

        # 🔴 THE EXEMPTION IS FROM *UNKNOWN*, NOT FROM *NO*, AND THAT NARROWING IS NOT A
        # DETAIL. Rick ruled "allow exact matches to run"; he did not rule "serve an answer
        # the user told us was wrong", and those are different sentences. All 103 refusals
        # in the corpus read `exact_hit:None` — nobody has ever recorded a False — so the
        # exemption below clears every one of them while an explicit rejection still stands.
        # CAUGHT HERE BY `test_9b_the_read_guard.py`'s parametrized
        # `test_an_exact_hit_is_served_when_UNKNOWN_and_refused_when_the_user_said_NO`, which
        # drives THIS `AskFlow` and asserts both arms — `None` served, `False` refused.
        # ⚠️ The queue carries its OWN copy of this exemption and its OWN guard,
        # `test_an_exact_hit_the_user_marked_WRONG_is_refused` in
        # `test_running_fifo_queue.py`. Two exemptions, two guards: reverting one does not
        # redden the other's test, so do not read either citation as covering both.
        # The blanket form served a known-wrong answer forever, which is a worse defect
        # than the one being fixed.
        if why == "exact_hit" and verdict is not False:
            trace.set( "replay_exact_match_exempt", True )
            return True

        if verdict is True:
            return True
        trace.set( "replay_refused_unconfirmed", f"{why}:{verdict!r}" )
        return False

    # THE COMMANDS THE ROUTER ITSELF CHOSE. Everything else reached `_run_agent` because
    # a CALLER named the command, and a caller's choice is not evidence about the
    # question. "resumed" belongs here: the router picked that command on the original
    # ask, and resume only folds in the answer to the argument it was missing.
    _ROUTER_CHOSE = frozenset( { "args_none", "args_complete", "resumed" } )

    # THE RECEPTIONIST IS A DESTINATION, NOT ONLY A FALLBACK.
    #
    # "agent router go to receptionist" is a SELECTABLE command — it sits in the served
    # command list and carries its own training utterances ("Switch to receptionist",
    # "Receptionist, please"). But its spec is cls=CommandClass.NONE with factory=None,
    # so `resolve()` returns None and `resolve_agentic()` does not serve it either, and
    # the flow reached the receptionist through the DEGRADE door answering
    # route_reason="unknown_command".
    #
    # So a user who ASKED FOR the receptionist was answered as though routing had FAILED,
    # and a deliberate pick, a garbage command and an unroutable question were identical
    # on path, route_reason AND command — `_receptionist` overwrites the caller's command
    # with its own on the way out, so the emitted command cannot tell them apart either.
    # `path` is what the notification card renders on, which makes the conflation
    # user-visible rather than merely internal.
    #
    # The fix is a LABEL, not a route: same path, same receptionist, a route_reason that
    # says which door was used. Giving the receptionist a factory was considered and
    # rejected — that would change what cls=NONE MEANS and pull it inside the write-back
    # guard, a semantics change bought to fix a labelling problem.
    RECEPTIONIST_COMMAND = "agent router go to receptionist"

    @classmethod
    def _unresolved_routed_command( cls, command: str ) -> Optional[ str ]:
        """The route to record for a command that did not resolve.

        A command that failed to resolve usually means no route was chosen, and recording it would assert a decision the router did not make. One sub-case is a real route: the receptionist is a positive choice in the router's own command list, so user_picked_receptionist means somebody selected it. Recording None there would throw away a real route.
        It derives from _unresolved_route_reason rather than re-deriving, because two copies of "is this the deliberate pick" would drift.

        Requires:
            - command is the command the router or the caller named

        Ensures:
            - returns the command when it is the deliberate receptionist pick
            - returns None otherwise; route_reason already says which door it was
        """
        return command if cls._unresolved_route_reason( command ) == "user_picked_receptionist" else None

    @classmethod
    def _unresolved_route_reason( cls, command: str ) -> str:
        """Say why an unresolvable command is going to the receptionist.

        It reads the incoming command, never the emitted one. The degrade callers pass their own literal reason and never reach this helper, so the marker cannot be set by a degrade.
        On submit the caller hands over the command, so a deliberate pick is literal. On ask the command is the router's output. The marker then means the router classified the utterance as asking for the receptionist: a model prediction, not a click.
        That is still the right label. The router's command list carries an explicit none for "I cannot place this", which resolves here to unknown_command. So the receptionist is a positive choice there. A low-confidence router lands on none. A misclassification is a wrong routing decision, not a wrong label.

        Requires:
            - command is the command the router or the caller named

        Ensures:
            - returns "user_picked_receptionist" only when that command is the
              receptionist, i.e. somebody asked for it by name
            - returns "unknown_command" otherwise
        """

        return "user_picked_receptionist" if command == cls.RECEPTIONIST_COMMAND else "unknown_command"

    @classmethod
    def _write_guard( cls, trace: StageTrace, spec: Any, route_reason: str, may_cache: bool ) -> bool:
        """The write guard: two refusals that only narrow may_cache, never widen it.

        1. The router must have chosen the agent. A submit caller hands over a command it decided on, so a row it wrote would say "this agent answers that question" on the caller's authority alone. The user overrode the router, so the result is not evidence about the question and is not cached.
        2. A CRUD-capable command is never cached, whatever the flag says. resolve() returns snapshotable=False for a command it forks to a CRUD agent only when `crud for dataframes agents enabled` is on. With the flag off the plain spec keeps snapshotable=True while spec.factory is TodoListAgent or CalendaringAgent. Keying on crud_factory asks the durable question, whether the command is about mutable user data, and answers the same with the flag either way.
        Both refusals are recorded in the trace, because a row that is not written leaves nothing behind to explain itself.
        """
        if not may_cache:
            return False
        if route_reason not in cls._ROUTER_CHOSE:
            trace.set( "writeback_refused_caller_chose_the_agent", route_reason )
            return False
        # PLAIN ATTRIBUTE ACCESS, NOT A DEFAULTED READ (Pocholo, on 92ed2565). Every spec
        # the registry can return carries `crud_factory` under both flag states — measured,
        # not assumed — so a fallback would be unreachable today AND would fail in the one
        # direction this check must never fail: a future spec type without the attribute
        # would be silently treated as non-CRUD and the guard would fail OPEN. Reading it
        # plainly fails loud instead. (The READ guard's `answer_is_correct` is the opposite
        # case — absent there means REFUSE, so a defaulted read is correct there.)
        if spec.crud_factory is not None:
            trace.set( "writeback_refused_crud_command", spec.factory.__name__ )
            return False
        return True

    def _receptionist( self, trace: StageTrace, question: str, ctx: tuple, route_reason: str,
                       primary_error: Optional[ str ]=None,
                       replayed_snapshot_id: Optional[ str ]=None,
                       routed_command: Optional[ str ]=None ) -> dict:
        """Run the receptionist inline as the else branch; its failure is terminal.

        primary_error carries the failure that caused the degrade. Without it the emitted error is the fallback's. That says why the receptionist died and nothing about why the real agent did.
        routed_command is the route the router actually chose. It is None where no route resolved: router_error (the router answered "unknown") and the unknown_command doors. Their command string names nothing servable, and recording it would assert a route the router did not choose. route_reason already says which door it was.
        What ran is not lost. path is "receptionist" here and nowhere else in this flow, so it already marks the fallback.
        The replayed_snapshot_id rides the same seam. This method builds a new Outcome from the receptionist run. That discards every field of a failed replay's outcome, so the caller that ran the replay passes the id in.
        """
        if primary_error: trace.set( "primary_agent_error", primary_error )
        work    = Work( "receptionist", self._build_agent( self.receptionist_factory, question, ctx ),
                       ctx[ 0 ], ctx[ 1 ], ctx[ 2 ], snapshotable=False )
        outcome = self.executor.submit( work, trace )
        return self._finish( trace, "receptionist", route_reason, outcome, question, ctx,
                             command=routed_command, primary_error=primary_error,
                             replayed_snapshot_id=replayed_snapshot_id )

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
        if not self._is_replayable( outcome, agent_class_name ):
            trace.set( "writeback_skipped_unreplayable", agent_class_name )
            if self.debug: print( f"[v2] not writing back {agent_class_name}: no code, and run_code cannot serve it codeless" )
            return None
        user_id, user_email, session_id, websocket_id, _speak = ctx
        snapshot    = self.cache.snapshot_from_result(
            question=question, answer=outcome.answer_raw, answer_conversational=outcome.answer,
            routing_command=command, agent_class_name=agent_class_name,
            user_id=user_id, session_id=session_id,
            code=outcome.code, code_example=outcome.code_example, code_returns=outcome.code_returns,
        )
        snapshot_id = self.cache.write_back( snapshot, writeback_enabled=self.writeback_enabled )
        if snapshot_id is not None:
            trace.mark( "t_writeback" )
        return snapshot_id

    @staticmethod
    def _is_replayable( outcome: Any, agent_class_name: str ) -> bool:
        """Say whether a row written from this outcome could ever be served back.

        This is the safety net under the code fix. Persisting the agent's code is what makes v2 rows replayable. This refuses to write the ones that still could not be: an agent that produced no code and whose class run_code() cannot serve codeless.
        Such a row is dead on arrival. Every hit on it raises "Cannot execute empty code list", degrades to the receptionist, and the row sits in the table costing a read forever.
        The codeless set is imported from the module that decides it, so the writer and run_code cannot disagree about which classes need code.
        """
        if agent_class_name in CODELESS_AGENT_CLASSES:
            return True
        return bool( outcome.code ) and not all( str( line ).strip() == "" for line in outcome.code )

    def _finish(
        self, trace: StageTrace, path: str, route_reason: str, outcome: Any, question: str, ctx: tuple,
        command: str, cache_hit: bool=False, snapshotable: bool=False, agent_class_name: str="",
        primary_error: Optional[ str ]=None, agent_label: Optional[ str ]=None,
        replayed_snapshot_id: Optional[ str ]=None,
    ) -> dict:
        """Stamp first-useful, write back, speak, and emit the terminal result."""
        trace.mark( "t_first_useful" )
        snapshot_id = self._maybe_write_back( trace, question, command, outcome, snapshotable, agent_class_name, ctx )
        self._speak( trace, self._spoken_line( outcome, agent_label, path ), outcome.job_id, ctx )
        return self._emit(
            trace, path=path, status=outcome.status, route_reason=route_reason, answer=outcome.answer,
            answer_raw=outcome.answer_raw, command=command, ctx=ctx, job_id=outcome.job_id,
            snapshot_id=snapshot_id, cache_hit=cache_hit,
            replayed_snapshot_id=replayed_snapshot_id,
            error=self._compose_error( primary_error, outcome.error ),
            queue_position=outcome.queue_position,
        )

    @staticmethod
    def _compose_error( primary_error: Optional[ str ], fallback_error: Optional[ str ] ) -> Optional[ str ]:
        """Keep the cause of the degrade in the emitted error, not just the fallback's.
        """
        if not primary_error: return fallback_error
        if not fallback_error: return f"primary agent failed: {primary_error}"
        return f"primary agent failed: {primary_error} | receptionist: {fallback_error}"

    @staticmethod
    def _spoken_line( outcome: Any, agent_label: Optional[ str ], path: str ) -> Optional[ str ]:
        """Say what this exit speaks: the answer, or v1's ack when the work was queued.

        A queued job has no answer yet, so waiting speaks the ack instead of the answer, never as well. That keeps it to one spoken line per request whichever executor is wired.
        It returns None when a waiting outcome has no label to name, as with the receptionist. The v1 queue speaks a random filler line built from word lists on the queue. Reproducing it here would move queue-owned state into the flow.
        It also returns None on a queued replay, which is why it takes path. A queued replay looks like a queued new job (status waiting, truthy agent_label). It created no job, and v1 speaks the cached answer itself. Without this the request gets two spoken lines. Both replay branches call _finish with the literal path "replay". One check covers the exact-hit and near-match arms.

        Requires:
            - outcome carries `status` and `answer`
            - path is the same literal `_finish` was called with

        Ensures:
            - status != "waiting" -> outcome.answer, on every path including replay
              (a replay that already has its answer in hand still speaks it)
            - status == "waiting" and path == "replay" -> None (v1 speaks it)
            - status == "waiting" and no agent_label -> None (the receptionist)
            - otherwise -> the "New <agent> job..." ack
        """
        if outcome.status != "waiting":
            return outcome.answer
        # A REPLAY CREATED NO JOB, so there is no new job to announce. Ordered ahead
        # of the label check because a replay always HAS a label — the check below
        # would never reach it.
        if path == "replay":
            return None
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
               error: Optional[ str ]=None, replayed_snapshot_id: Optional[ str ]=None,
               queue_position: Optional[ int ]=None, submit_details: Optional[ dict ]=None ) -> dict:
        """Assemble the response dict and write the authoritative trace line.

        It stamps t_complete here, the single chokepoint every terminal exit funnels through: agent, replay and receptionist via _finish, needs_input, resume's interview-continue, and the expired refusal. So t_recv to t_complete is the completion-symmetric span for v1's running-to-completed.
        _finish calls _maybe_write_back before _emit, so t_complete is always stamped after the snapshot write. It follows _speak on the answer path, so a few microseconds of TTS dispatch fall inside v2's span. That bias is conservative: v2 reads slightly slower, never faster.
        """
        # ONE ROUTE MUST REACH THE OUTPUT VOCABULARY UNDER ONE NAME (row 759a895b).
        # `math` is a registered alias of `agent router go to math`, and resolve() honours
        # aliases -- so a router emitting the short form routed CORRECTLY and was then
        # recorded under its own spelling. Downstream counts grouped by payload.command
        # split silently, and an exact-match routing score marked a right route as a miss.
        # Canonicalised HERE because _emit is the single chokepoint every terminal exit
        # funnels through, so one line fixes every emitter. Deliberately NOT applied to
        # _route_reason, which reads the INCOMING command on purpose (see its docstring).
        command = canonical_command( command )
        trace.mark( "t_complete" )
        # WHICH ROW A REPLAY READ — its own field, never folded into `job_id` (row 7e2125a7).
        # `job_id` already carried this value on the SUCCESS path only, because the replay
        # Outcome's job_id IS the row's id_hash, while on the agent path the same key means
        # a QUEUE job. One key with two meanings cannot be grouped on; and the failures —
        # the rows that most need naming — carried neither. Measured in
        # eval-2026-08-21-11-37-48: job_id present on 85 of 85 exact_hit rows and 0 of 126
        # replay_error rows. `snapshot_id` is not the answer either: it is the WRITE-BACK
        # id, so it is null by construction on a warm pass that writes nothing back.
        trace.update( path=path, status=status, route_reason=route_reason, cache_hit=cache_hit,
                      wrote_snapshot=snapshot_id is not None,
                      replayed_snapshot_id=replayed_snapshot_id )
        trace.write()
        self._log_query( trace, ctx, snapshot_id=snapshot_id, cache_hit=cache_hit )
        result = {
            "path"        : path,           "status"       : status,        "route_reason" : route_reason,
            "answer"      : answer,         "answer_raw"   : answer_raw,     "command"      : command,
            "args_known"  : args_known or [], "args_missing": args_missing or [],
            "pending_id"  : pending_id,     "job_id"       : job_id,         "snapshot_id"  : snapshot_id,
            "similarity"  : trace.fields.get( "similarity" ),               "wrote_snapshot": snapshot_id is not None,
            "cache_hit"   : cache_hit,      "spoke"        : trace.has_mark( "t_tts_dispatch" ),
            "replayed_snapshot_id" : replayed_snapshot_id,
            "timings_ms"  : trace.timings_ms(),                             "trace_id"     : trace.trace_id,
            "error"       : error,
        }
        # ADDED ONLY WHEN THERE IS ONE (row a3c59f2d): a job was just queued and its place
        # is known. Absent otherwise, so the result dict every other path returns keeps
        # exactly the keys it had; `AskResponse.queue_position` defaults to null.
        if queue_position is not None: result[ "queue_position" ] = queue_position
        if submit_details is not None: result[ "submit_details" ] = submit_details
        return result
