#!/usr/bin/env python3
"""
Runtime Argument Expeditor - Core Logic.

Sits between LORA intent classification and agentic job creation.
When a user says "make me a podcast", the LORA model identifies the routing
command but may not capture all required arguments. The expeditor detects
missing args via LLM gap analysis against --help output, then asks the user
for missing information via synchronous voice notifications.

Scope: Deep Research, Podcast Generator, Research-to-Podcast (3 agents).
"""

import json
import os
import re
from dataclasses import dataclass
from typing import Optional

import cosa.utils.util as cu

from cosa.agents.runtime_argument_expeditor.agent_registry import (
    JOB_ARG_CONTRACTS,
    DEFAULT_FILE_EXTENSIONS,
    DEFAULT_FILE_SEARCH_ROOTS,
    get_cli_help,
    get_user_visible_args
)
from cosa.agents.runtime_argument_expeditor.xml_models import ExpeditorResponse, ArgConfirmationResponse
from cosa.agents.llm_client_factory import LlmClientFactory
from cosa.agents.io_models.utils.prompt_template_processor import PromptTemplateProcessor
from cosa.agents.io_models.utils.fuzzy_file_prefilter import prefilter_docs_map_by_keywords, dominant_keyword_match
from lupin_cli.notifications.notify_user_sync import notify_user_sync
from lupin_cli.notifications.notification_models import (
    NotificationRequest,
    NotificationPriority,
    ResponseType
)
from cosa.utils.notification_utils import (
    format_open_ended_batch_for_tts,
    convert_open_ended_batch_for_api
)


# --------------------------------------------------------------------------- #
# Why a batch collection came back without answers (bug 2aaab1bf).
#
# `None` alone cannot carry a reason. Collapsing every outcome into it is what
# let a TRANSPORT failure be reported as a USER decision: a 503 (the prompt could
# not be delivered, so the user was never asked) printed as "User cancelled
# batch collection" and killed the job as "cancelled by user or timeout".
#
# Only DECLINED represents an actual human choice. The rest are failures of the
# machinery and must never be reported as something the user did.
# --------------------------------------------------------------------------- #
BATCH_ANSWERED    = "answered"      # got every arg asked for
BATCH_DECLINED    = "declined"      # the USER said no — the ONLY reason that is a user decision
BATCH_UNREACHABLE = "unreachable"   # could not deliver — the user was never asked (no live socket)
BATCH_TIMEOUT     = "timeout"       # delivered or not, the budget elapsed with no answer
BATCH_MALFORMED   = "malformed"     # delivered, but the response could not be parsed
BATCH_INCOMPLETE  = "incomplete"    # answered, but a required arg came back missing or blank
BATCH_INTERNAL    = "internal"      # setup failed before the user could be asked (e.g. unknown command)


@dataclass
class ExtractionResult:
    """
    The non-interactive half of expedite() — everything collect() needs to
    drive user interaction, with zero prompts issued yet.

    Requires:
        - final_args is a dict of arg-name -> value already resolved (LORA +
          LLM merge)
        - missing is the list of user-visible arg names still to collect
        - fallback_questions / fallback_defaults / special_handlers are the
          agent-entry maps that govern how each missing arg is collected

    Ensures:
        - Carries no interaction state; safe to build without a live user socket
    """
    final_args         : dict
    missing            : list
    fallback_questions : dict
    fallback_defaults  : dict
    special_handlers   : dict


@dataclass
class ExpediteContext:
    """
    Everything that belongs to ONE expedite() call, carried as an argument.

    The expeditor is shared — v2 keeps a single instance on app.state — so a
    caller's job id, bearer token and failure reason must never live on the
    instance. They used to (`self._job_id` / `self._bearer_token` /
    `self._last_expedite_reason` / `self._last_notification_status`), which
    worked only because v1 built a fresh expeditor per request. Two requests in
    flight at once shared those four slots, and the second caller's bearer token
    was the one the first caller's notification went out with (row 10c60712).

    Requires:
        - job_id / bearer_token are the CALLER's own, or None
        - one instance per expedite() call, never reused across calls

    Ensures:
        - Carries values IN (job_id, bearer_token) and results OUT (reason,
          notification_status) for exactly one call
        - Two concurrent calls share nothing

    Note on the helpers' `context=None` default: a helper called without one
    builds a throwaway, so it sends no token and drops the reason. That is a
    DEGRADED call, never a crossover — the failure mode of forgetting to pass
    the context is an unauthenticated notification, not another user's
    credential. The default exists for direct unit-level calls; every path from
    expedite()/collect() passes the caller's own.
    """
    job_id              : str = None
    bearer_token        : str = None
    reason              : str = None    # one of the BATCH_* constants, or None on success
    notification_status : str = None    # the last notification response's status


@dataclass
class ArgSpec:
    """
    An JOB_ARG_CONTRACTS entry, typed — every field the expeditor's extract() /
    collect() halves and their helpers read, in one carrier. The expedite() shim
    builds one from the raw table entry, so the whole pipeline runs off the spec
    and a v2 caller can drive it (including resolving a display name) with no
    registry entry at all. Not a minimal slice: it carries the entry's readable
    surface so nothing downstream has to reach back into the table.

    Requires:
        - arg_mapping maps LORA arg names -> CLI arg names
        - system_provided / required_user_args are lists of arg-name strings
        - fallback_questions maps arg-name -> question text
        - fallback_defaults maps arg-name -> default value (may start empty; a
          COPY of the registry entry's dict per bug 8aa89f42, so extract()'s
          in-place seeding never leaks one user's default to the next)
        - special_handlers maps arg-name -> handler tag
        - file_args maps arg-name -> its typed declaration ({ kind, search_roots,
          search_paths_key }); empty for an agent with no file-typed argument
        - display_name is the human agent name, or None (derived from cli_module)
        - cli_module is the agent's CLI module path, or None (test_suite has none
          by design — invoked via API, not CLI)

    Ensures:
        - Holds references (except the copied fallback_defaults); behavior matches
          reading the raw dict
    """
    arg_mapping        : dict
    system_provided    : list
    required_user_args : list
    fallback_questions : dict
    fallback_defaults  : dict
    special_handlers   : dict
    display_name       : str
    cli_module         : str
    file_args          : dict

    @classmethod
    def from_entry( cls, entry ):
        """
        Build an ArgSpec from a raw JOB_ARG_CONTRACTS entry, preserving the exact
        reference semantics the expeditor relied on when it read the dict directly.

        Requires:
            - entry is an JOB_ARG_CONTRACTS registry entry (has arg_mapping,
              system_provided, required_user_args, fallback_questions)

        Ensures:
            - fallback_defaults is a COPY of the entry's dict (bug 8aa89f42): the
              seam is the one place extract() later writes, so copying here keeps
              one user's seeded default from becoming the next user's default for
              the life of the process, while the registry entry stays unmutated
            - special_handlers / the other fields use the entry's own object
              (they are only read, never written)
            - display_name / cli_module default to None when absent, matching the
              former entry.get( key ) reads inside _resolve_display_name
        """
        return cls(
            arg_mapping        = entry[ "arg_mapping" ],
            system_provided    = entry[ "system_provided" ],
            required_user_args = entry[ "required_user_args" ],
            fallback_questions = entry[ "fallback_questions" ],
            fallback_defaults  = dict( entry.get( "fallback_defaults", {} ) ),
            special_handlers   = entry.get( "special_handlers", {} ),
            display_name       = entry.get( "display_name" ),
            cli_module         = entry.get( "cli_module" ),
            file_args          = entry.get( "file_args", {} ),
        )


# --------------------------------------------------------------------------- #
# First-turn document disambiguation (plan 2026.08.04-first-turn-document-
# disambiguation). When a workable number of documents match, show the SAME
# multiple-choice card the routing confirm already uses instead of a blank
# "which document?" question. The 5 is a UX judgment, NOT a technical limit —
# the same card renders more (the routing confirm shows ~11); a dozen file
# options just reads worse than a question, so beyond the cap we fall through
# to the open exact-path ask.
# --------------------------------------------------------------------------- #
MAX_CHOICE_OPTIONS           = 5
DOC_CHOICE_DESCRIBE_LABEL    = "Let me describe it instead"
DOC_CHOICE_CANCEL_LABEL      = "Cancel"
DOC_CHOICE_DESCRIBE_SENTINEL = "__describe_instead__"   # helper return: user opted for the open ask

# WHAT THIS CARD IS, said once and stably (row a1420538). The card's QUESTION is
# derived per calling agent — "for the podcast", "for the presentation" — which is
# right for the user and wrong as an identifier: the decision proxy's answer files
# matched on that prose, so every new agent needed its own byte-identical entry and a
# wording change silently left the card unanswered. The id says WHICH CARD this is
# regardless of who is asking, and rides in response_options, which the API carries
# through as an opaque dict (notifications.py json.loads it and passes it on) — no new
# model field, no endpoint change.
DOCUMENT_CHOICE_CARD_ID      = "document_choice"

# The OPEN-ENDED half of the same conversation (row 0c280989): "which document? —
# describe it or say the filename". Six proxy entries across six profiles were keyed on
# its prose, and unlike the card's two they had drifted into three different wordings.
# Same remedy, same reason. The id names the ASK, not the argument: podcast asks it for
# `research` and presentation for `source`, and one id with arg_name riding as metadata
# is what keeps that from becoming per-agent keying again.
DOCUMENT_DESCRIBE_ASK_ID     = "document_describe"


# --------------------------------------------------------------------------- #
# Turning a failure reason into what the user hears (bug 68198c9f).
#
# expedite() used to return a bare None on every failure, so the caller said one
# thing for all of them: "Agentic job cancelled by user or timeout." A prompt
# that could not be delivered — the user never saw it — was reported as the user
# cancelling. ONLY BATCH_DECLINED is a human decision; every other reason is a
# machine failure and must never be phrased as something the user did.
# --------------------------------------------------------------------------- #
def user_message_for_expedite_reason( reason ):
    """
    Map an expedite failure reason to the ( spoken, log_line ) the user gets.

    Requires:
        - reason is one of the BATCH_* strings, None, or any unknown string

    Ensures:
        - returns a 2-tuple of non-empty strings ( spoken, log_line )
        - ONLY BATCH_DECLINED produces a message that attributes the outcome
          to the user; every other reason (including None / unknown) is worded
          as a machine failure the user did not cause
    """
    messages = {
        BATCH_DECLINED    : ( "Okay, I've cancelled that job.",
                              "Agentic job cancelled: the user declined." ),
        BATCH_UNREACHABLE : ( "I couldn't reach you to confirm the details, so I held off on starting the job. Just ask again when you're ready.",
                              "Agentic job not started: the confirmation prompt could not be delivered (user had no live connection)." ),
        BATCH_TIMEOUT     : ( "I didn't hear back in time, so I didn't start the job. Just ask again when you're ready.",
                              "Agentic job not started: the confirmation timed out with no answer." ),
        BATCH_MALFORMED   : ( "I couldn't make out your answer, so I didn't start the job. Let's try that again.",
                              "Agentic job not started: the response could not be understood." ),
        BATCH_INCOMPLETE  : ( "I'm still missing some details, so I haven't started the job yet.",
                              "Agentic job not started: required details were incomplete." ),
        BATCH_INTERNAL    : ( "Something went wrong setting up that job, so I didn't start it.",
                              "Agentic job not started: internal error during argument expediting." ),
    }
    return messages.get(
        reason,
        ( "Something went wrong setting up that job, so I didn't start it.",
          "Agentic job not started: unrecognized expedite failure reason." )
    )


class RuntimeArgumentExpeditor:
    """
    Determines which required arguments a user's voice command provides and
    asks for any missing ones before creating an agentic job.

    Requires:
        - config_mgr is a valid ConfigurationManager instance
        - The config has keys: runtime argument expeditor enabled,
          llm spec key for runtime argument expeditor,
          prompt template for runtime argument expeditor

    Ensures:
        - expedite() returns a complete args dict or None (cancel/timeout)
        - Uses LLM only for gap analysis; questions come from static registry
        - System-provided args are never asked for
    """

    SENDER_ID = "arg.expeditor@lupin.deepily.ai"

    def __init__( self, config_mgr, debug=False, verbose=False ):
        """
        Initialize the runtime argument expeditor.

        Requires:
            - config_mgr is a valid ConfigurationManager instance

        Ensures:
            - Reads 3 config keys
            - Creates LlmClientFactory singleton reference

        Args:
            config_mgr: ConfigurationManager instance
            debug: Enable debug output
            verbose: Enable verbose output
        """
        self.config_mgr                = config_mgr
        self.debug                     = debug
        self.verbose                   = verbose
        self.llm_spec_key              = config_mgr.get( "llm spec key for runtime argument expeditor" )
        self.prompt_template_path      = config_mgr.get( "prompt template for runtime argument expeditor" )
        self.confirmation_prompt_path  = config_mgr.get( "prompt template for argument confirmation" )
        self.llm_factory               = LlmClientFactory( debug=debug, verbose=verbose )
        # NOTHING per-call lives here. Why a call ended without a complete args
        # dict — one of the BATCH_* constants — rides on the caller's own
        # ExpediteContext, so an UNREACHABLE / TIMEOUT job is never recorded as a
        # user cancellation (bugs 2aaab1bf, 68198c9f) AND one caller's reason is
        # never readable by another (row 10c60712).

    @staticmethod
    def _classify_ask_failure( response ):
        """
        Classify a failed/empty notification response into a machine-failure reason.

        Requires:
            - response has .success, .is_timeout attributes

        Ensures:
            - NEVER returns BATCH_DECLINED — a decline is a parsed user answer,
              detected by the caller, not a failed delivery
            - is_timeout            -> BATCH_TIMEOUT
            - delivered but empty   -> BATCH_MALFORMED (exit 0, no usable value)
            - otherwise             -> BATCH_UNREACHABLE (never delivered)
        """
        if response.is_timeout:
            return BATCH_TIMEOUT
        if response.success:
            return BATCH_MALFORMED
        return BATCH_UNREACHABLE

    def expedite( self, command, raw_args, user_email, session_id, user_id, original_question, job_id=None, bearer_token=None, context=None ):
        """
        Run argument gap analysis and collect missing arguments from user.

        Requires:
            - command is a key in JOB_ARG_CONTRACTS
            - raw_args is a string (may be empty)
            - user_email, session_id, user_id are non-empty strings
            - original_question is the full voice command string

        Ensures:
            - Returns dict of complete args if all required args are satisfied
            - Returns None if user cancels, times out, or command not found
            - System-provided args are injected, never asked for

        Args:
            command: Routing command key (e.g., "agent router go to deep research")
            raw_args: LORA-extracted arguments string
            user_email: Authenticated user's email
            session_id: WebSocket session ID
            user_id: System user ID
            original_question: Full voice command transcription
            job_id: Optional agentic job ID for routing notifications to job cards
            bearer_token: Optional JWT for authenticating notification requests
            context: Optional ExpediteContext the caller owns. Pass one to read
                back WHY the call failed (`context.reason`) and the last
                notification status; omit it and that outcome is discarded. It
                is the caller's object, not the expeditor's — two concurrent
                calls each read their own.

        Returns:
            dict or None: Complete argument dictionary or None on cancel
        """
        context              = context if context is not None else ExpediteContext()
        context.job_id       = job_id
        context.bearer_token = bearer_token
        context.reason       = None

        agent_entry = JOB_ARG_CONTRACTS.get( command )
        if not agent_entry:
            print( f"[Expeditor] Unknown command: {command}" )
            context.reason = BATCH_INTERNAL
            return None

        spec       = ArgSpec.from_entry( agent_entry )
        extraction = self.extract( command, raw_args, original_question, spec )
        return self.collect(
            extraction, command, original_question, spec,
            user_email, session_id, user_id, context=context
        )

    def extract( self, command, raw_args, original_question, spec ):
        """
        Non-interactive half of expedite(): resolve known args and compute what
        is still missing. Issues NO user prompts.

        Requires:
            - command is a key in JOB_ARG_CONTRACTS
            - raw_args is a string (may be empty)
            - original_question is the full voice command string
            - spec is an ArgSpec built from the command's registry entry (by the
              caller) — extract() reads only spec, never the JOB_ARG_CONTRACTS table

        Ensures:
            - Returns an ExtractionResult carrying final_args (LORA + LLM merge),
              the list of still-missing user-visible args, and the fallback /
              special-handler maps collect() needs
            - Does not prompt the user or touch any notification socket

        Args:
            command: Routing command key (e.g., "agent router go to deep research")
            raw_args: LORA-extracted arguments string
            original_question: Full voice command transcription
            spec: ArgSpec carrying the fields extract() reads for command

        Returns:
            ExtractionResult
        """
        # Step 1: Capture --help output
        help_text = get_cli_help( command )
        if not help_text:
            help_text = "(CLI help not available)"

        # Step 2: Parse LORA args and map to CLI names
        lora_args    = self._parse_lora_args( raw_args )
        mapped_args  = {}
        arg_mapping  = spec.arg_mapping

        for lora_name, value in lora_args.items():
            cli_name = arg_mapping.get( lora_name, lora_name )
            mapped_args[ cli_name ] = value

        if self.debug:
            print( f"[Expeditor] LORA args: {lora_args}" )
            print( f"[Expeditor] Mapped args: {mapped_args}" )

        # Step 3: Build and run LLM gap analysis prompt
        template_raw = cu.get_file_as_string(
            cu.get_project_root() + self.prompt_template_path
        )

        # Process {{PYDANTIC_XML_EXAMPLE}} first
        processor = PromptTemplateProcessor( debug=self.debug )
        template_processed = processor.process_template(
            template_raw, "runtime argument expeditor"
        )

        # Fill runtime placeholders
        system_args   = ", ".join( spec.system_provided )
        required_args = ", ".join( spec.required_user_args )
        extracted_str = ", ".join( f"{k}={v}" for k, v in mapped_args.items() ) if mapped_args else "(none)"

        prompt = template_processed.format(
            system_args    = system_args,
            help_text      = help_text,
            voice_command  = original_question,
            extracted_args = extracted_str,
            required_args  = required_args
        )

        if self.debug and self.verbose:
            print( f"[Expeditor] Prompt ({len( prompt )} chars):\n{prompt[ :500 ]}..." )

        # Step 4: Call LLM
        llm_client = self.llm_factory.get_client(
            self.llm_spec_key, debug=self.debug, verbose=self.verbose
        )
        response = llm_client.run( prompt )

        if self.debug: print( f"[Expeditor] LLM response: {response[ :300 ]}" )

        # Step 5: Parse response
        try:
            parsed = ExpeditorResponse.from_xml( response )
        except Exception as e:
            print( f"[Expeditor] Failed to parse LLM response: {e}" )
            # Fallback: assume all required args are missing
            parsed = ExpeditorResponse(
                all_required_met = "false",
                args_present     = "",
                args_missing     = ", ".join( spec.required_user_args )
            )

        # Step 6: Merge LLM-detected present args with LORA-mapped args
        present_dict = parsed.get_present_dict()

        final_args = dict( mapped_args )
        for k, v in present_dict.items():
            if k not in final_args:
                final_args[ k ] = v

        if self.debug: print( f"[Expeditor] Args after LLM merge: {final_args}" )

        # Step 7: Compute missing user-visible args deterministically
        # This replaces the old if/else gate on parsed.is_complete() which
        # skipped optional arg prompting when all required args were present.
        user_visible       = get_user_visible_args( command )
        fallback_questions = spec.fallback_questions
        fallback_defaults  = spec.fallback_defaults
        special_handlers   = spec.special_handlers

        # Fallback: if CLI doesn't publish user-visible-args, use fallback_questions keys
        if user_visible is None:
            user_visible = list( fallback_questions.keys() )

        # Missing = user-visible args not yet in final_args
        missing = [ arg for arg in user_visible if arg not in final_args ]

        # Pre-populate fallback defaults for required args that have no default.
        # The user's original question is the best default for "task" or "query" fields.
        required_args = spec.required_user_args
        for arg_name in required_args:
            if arg_name in missing and arg_name not in fallback_defaults:
                fallback_defaults[ arg_name ] = original_question

        if self.debug: print( f"[Expeditor] Missing user-visible args: {missing}" )

        return ExtractionResult(
            final_args         = final_args,
            missing            = missing,
            fallback_questions = fallback_questions,
            fallback_defaults  = fallback_defaults,
            special_handlers   = special_handlers,
        )

    def collect( self, extraction, command, original_question, spec, user_email, session_id, user_id, *, context ):
        """
        Interactive half of expedite(): prompt the user for the args extract()
        found missing, run any special handlers, confirm, and inject system args.

        Requires:
            - extraction is an ExtractionResult from extract()
            - command is a key in JOB_ARG_CONTRACTS and spec is its ArgSpec
            - user_email, session_id, user_id are non-empty strings
            - original_question is the full voice command string

        Ensures:
            - Returns the complete injected argument dict on success
            - Returns None on user cancel / decline / timeout / transport failure
            - On a non-user-decision failure, records the cause on context.reason
              and does not report it as a cancellation (bug 2aaab1bf)

        Args:
            extraction: ExtractionResult carrying final_args + missing + maps
            command: Routing command key
            original_question: Full voice command transcription
            spec: ArgSpec for command (extract() + collect() run off the spec)
            user_email: Authenticated user's email
            session_id: WebSocket session ID
            user_id: System user ID
            context: THIS call's ExpediteContext (required — it carries the
                caller's bearer token down and the failure reason back up)

        Returns:
            dict or None: Complete argument dictionary or None on cancel
        """
        final_args         = extraction.final_args
        missing            = extraction.missing
        fallback_questions = extraction.fallback_questions
        fallback_defaults  = extraction.fallback_defaults
        special_handlers   = extraction.special_handlers

        if missing:
            # Partition missing args into batchable and special
            batchable = []
            special   = []
            for arg_name in missing:
                if special_handlers.get( arg_name ):
                    special.append( arg_name )
                else:
                    batchable.append( arg_name )

            # Build request context abstract for notification UI
            request_abstract = self._build_request_context(
                spec, command, original_question, final_args, batchable + special
            )

            # Batch-collect batchable args if more than one
            if len( batchable ) > 1:
                if self.debug: print( f"[Expeditor] Batch-collecting {len( batchable )} args: {batchable}" )
                batch_answers, batch_reason = self._batch_collect_args( batchable, fallback_questions, user_email, fallback_defaults, command, abstract=request_abstract, context=context )
                if batch_answers is None:
                    context.reason = batch_reason
                    if batch_reason == BATCH_DECLINED:
                        print( "[Expeditor] User declined batch collection" )
                    else:
                        # NOT a user decision. Say so, and say what actually happened —
                        # reporting a transport failure as a cancellation is the defect
                        # this branch exists to prevent (bug 2aaab1bf).
                        print( f"[Expeditor] Batch collection did NOT reach a user decision: {batch_reason} "
                               f"(notification status: {context.notification_status}). "
                               f"The user did not cancel — the prompt never got a usable answer." )
                    return None
                for arg_name, value in batch_answers.items():
                    # Handle special "no limit" / "none" answers for optional args
                    if arg_name in ( "budget", "languages", "timeout" ) and value.lower().strip() in ( "no limit", "none", "skip", "no", "default" ):
                        continue
                    final_args[ arg_name ] = value
            elif len( batchable ) == 1:
                # Single arg — use existing sequential flow
                arg_name = batchable[ 0 ]
                resolved_default = self._resolve_default( command, arg_name, fallback_defaults.get( arg_name ) )
                if arg_name in fallback_questions:
                    value = self._ask_for_arg( arg_name, fallback_questions[ arg_name ], user_email, response_default=resolved_default, abstract=request_abstract, context=context )
                else:
                    value = self._ask_for_arg( arg_name, f"Please provide the '{arg_name}' argument.", user_email, response_default=resolved_default, abstract=request_abstract, context=context )
                if value is None:
                    print( f"[Expeditor] User cancelled at arg '{arg_name}'" )
                    return None
                if arg_name in ( "budget", "languages", "timeout" ) and value.lower().strip() in ( "no limit", "none", "skip", "no", "default" ):
                    pass  # Skip optional
                else:
                    final_args[ arg_name ] = value

            # Handle special args sequentially (e.g., fuzzy_file_match)
            for arg_name in special:
                handler = special_handlers[ arg_name ]
                if handler == "fuzzy_file_match":
                    # Auto-resolve (row bd0ce120) and the first-turn choice card were
                    # both gated on `command == podcast` while the behaviour was proven
                    # on that one route. Row 5bc22180 removes the gate: EVERY
                    # fuzzy_file_match consumer forwards the utterance and opts into the
                    # card, because nothing in either step is podcast-specific — they
                    # are generic file resolution. The presentation generator's `source`
                    # was the degraded member; TFE's `resume_from` is untouched because
                    # it routes through a different handler on the elif below, not
                    # because a command check protects it.
                    #
                    # arg_name/ask_question carry the CALLING agent's own identity into
                    # the prompt. Previously both were hardcoded to the podcast's, so a
                    # presentation job asked "Which document should I use for the
                    # podcast?" under a card titled "Missing: research" (row ea184d06).
                    # Wording only — the matching logic above is untouched.
                    fuzzy_question = spec.fallback_questions.get( arg_name )
                    value = self._handle_fuzzy_file_match(
                        user_email, spec.display_name,
                        original_question=original_question, use_choice_card=True,
                        arg_name=arg_name, ask_question=fuzzy_question,
                        file_arg=spec.file_args.get( arg_name ), context=context
                    )
                    # Auto-detect YAML → set render_only flag
                    if value and value.lower().endswith( ( ".yaml", ".yml" ) ):
                        final_args[ "render_only" ] = "true"
                        if self.debug: print( f"[Expeditor] YAML detected → render_only=true" )
                elif handler == "tfe_checkpoint_match":
                    # Session 9056c113 doc 16 Phase 2 — voice-driven TFE resume.
                    # Fuzzy-match user description against stalled/recent TFE jobs.
                    value = self._handle_tfe_checkpoint_match( user_email, context=context )
                else:
                    value = self._ask_for_arg( arg_name, f"Please provide the '{arg_name}' argument.", user_email, abstract=request_abstract, context=context )
                if value is None:
                    print( f"[Expeditor] User cancelled at arg '{arg_name}'" )
                    return None
                final_args[ arg_name ] = value

        # Fix B (row bd0ce120): a special-handler arg can be PRESENT yet still
        # unresolved. The LLM merge fills `research` with a bare topic word
        # ("KISS") extracted from a natural utterance, so it is NOT in `missing`
        # above and its fuzzy handler is skipped — then the bare topic is handed
        # downstream where a file path is expected and the job dies with
        # FileNotFoundError at runtime (podcast_generator/job.py:216-223). Treat a
        # present-but-non-existing-path value as UNRESOLVED and run the same fuzzy
        # matcher the missing case uses. The matcher SEED is original_question (the
        # full utterance, the validated input), not the bare pre-filled value; a
        # zero-or-2+ match falls through to the "which document?" prompt inside
        # _handle_fuzzy_file_match, never a crash.
        #
        # Row 5bc22180 removed the `command == podcast` gate that used to wrap this
        # loop. The presentation generator hit the SAME defect through `source`, one
        # step earlier: presentation_generator/job.py pre-validates the path and
        # raises FileNotFoundError("Source document not found: KISS") before the
        # orchestrator is built, so the job ended FAILED. Nothing in the loop is
        # podcast-specific — the `handler != "fuzzy_file_match"` line is what keeps
        # TFE's `resume_from` out, and that line does the job on its own.
        for arg_name, handler in special_handlers.items():
            if handler != "fuzzy_file_match":                          continue
            if arg_name in missing:                                    continue  # the missing-loop above already ran its handler — never re-resolve
            if arg_name not in final_args:                             continue  # not present at all — nothing to resolve
            if self._value_is_existing_path( final_args[ arg_name ] ): continue  # already a real path — leave it
            if self.debug: print( f"[Expeditor] Present-but-unresolvable '{arg_name}'={final_args[ arg_name ]!r} → running fuzzy resolve" )
            # The caller's OWN arg name and question, exactly as the missing-arg loop
            # passes them. Omitting them here left the rescue on the handler's podcast
            # defaults, which is how a presentation job came to ask about "the podcast"
            # under a card titled "Missing: research" (job pr-a10a55aa).
            value = self._handle_fuzzy_file_match(
                user_email, spec.display_name,
                original_question=original_question, use_choice_card=True,
                arg_name=arg_name, ask_question=spec.fallback_questions.get( arg_name ),
                file_arg=spec.file_args.get( arg_name ), context=context
            )
            if value is None:
                print( f"[Expeditor] User cancelled resolving present-but-unresolvable arg '{arg_name}'" )
                return None
            final_args[ arg_name ] = value
            if value.lower().endswith( ( ".yaml", ".yml" ) ):
                final_args[ "render_only" ] = "true"
                if self.debug: print( f"[Expeditor] YAML detected → render_only=true" )

        if self.debug: print( f"[Expeditor] Final args: {final_args}" )

        # Step 8: Confirmation loop — user reviews args before submission
        confirmed_args = self._confirm_and_iterate( final_args, spec, command, user_email, context=context )
        if confirmed_args is None:
            print( "[Expeditor] User cancelled during confirmation" )
            return None

        return self._inject_system_args(
            confirmed_args, spec, user_email, session_id, user_id
        )

    @staticmethod
    def _value_is_existing_path( value ):
        """
        True iff ``value`` names a file/dir that exists on disk.

        Mirrors the podcast job's own research-path check
        (podcast_generator/job.py:216-223): absolute values are tested as-is;
        relative values are resolved against the project root. A bare topic word
        ("KISS") returns False — the signal, used by Fix B (row bd0ce120), that a
        special-handler arg is present-but-unresolved and must be run through the
        fuzzy matcher rather than handed downstream as a path.

        Requires:
            - value is a string or None

        Ensures:
            - returns False for None/empty
            - returns os.path.exists() of the project-root-resolved value otherwise
        """
        if not value:
            return False
        full_path = value if value.startswith( "/" ) else cu.get_project_root() + "/" + value
        return os.path.exists( full_path )

    @staticmethod
    def _resolve_display_name( spec ):
        """
        Resolve a human-readable agent name from an ArgSpec.

        Prefers explicit ``display_name``. Falls back to deriving from
        ``cli_module`` (e.g. ``cosa.agents.podcast_generator.cli`` →
        "podcast generator"). Returns "agent" if neither is set.

        Bugfix 2026-04-30 (Session b195a160 — Cluster J of 2026.04.29 postmortem):
        the prior single-expression
        ``agent_entry.get("display_name", agent_entry["cli_module"].split(...))``
        eagerly evaluated the default arm even when display_name was present,
        crashing with "'NoneType' object has no attribute 'split'" for the
        ``test_suite`` registry entry where ``cli_module=None`` by design
        (test_suite is invoked directly via API, not via CLI). See
        src/rnd/v0.1.7/2026.04.30-postmortem-2026.04.29-all-test-run.md §J.
        """
        if spec.display_name:
            return spec.display_name
        if spec.cli_module:
            return spec.cli_module.split( "." )[ -1 ].replace( "_", " " )
        return "agent"

    def _confirm_and_iterate( self, args_dict, spec, command_key, user_email, *, context=None ):
        """
        Present argument summary and iterate until user approves, modifies, or cancels.

        Uses YES_NO prompt type. Summary is shown via abstract (not spoken).
        Spoken message is a clean question. User comments carry modification intent.

        Requires:
            - args_dict contains all collected user-facing args
            - spec is the ArgSpec for this agent
            - command_key is the agent's key in JOB_ARG_CONTRACTS

        Ensures:
            - Returns approved args_dict, or None if cancelled
            - User has seen and approved all arguments before submission
            - Only user-visible args are shown (whitelist from CLI)
            - Maximum 5 iterations to prevent infinite loops
            - "yes" approves, "no" cancels
            - "yes [comment: ...]" applies tweak then proceeds
            - "no [comment: ...]" applies tweak then re-presents

        Args:
            args_dict: Collected argument dictionary
            spec: ArgSpec for the target agent
            command_key: Key in JOB_ARG_CONTRACTS for user-visible-args lookup
            user_email: Target user for voice prompts
            context: THIS call's ExpediteContext (see ExpediteContext)

        Returns:
            dict or None: Approved args_dict or None on cancel
        """
        context = context if context is not None else ExpediteContext()
        max_iterations = 5

        # Whitelist: only show user-visible args in confirmation summary
        user_visible = get_user_visible_args( command_key )
        # Fallback: if agent doesn't publish, use fallback_questions keys
        if user_visible is None:
            user_visible = list( spec.fallback_questions.keys() )

        for iteration in range( max_iterations ):
            # Build summary of user-visible args only → abstract (shown, not spoken)
            summary_lines = []
            for k, v in args_dict.items():
                if k in user_visible:
                    summary_lines.append( f"- **{k}**: {v}" )

            agent_name = self._resolve_display_name( spec )

            # Runtime scheduling section (universal, not agent-specific)
            summary_lines.append( "" )
            summary_lines.append( "---" )
            summary_lines.append( "**Scheduling**" )
            summary_lines.append( f"- **run_at**: { args_dict.get( 'scheduled_at', 'immediately' ) }" )
            summary_lines.append( f"- **exclusive_mode**: { 'yes' if args_dict.get( 'monopolize' ) else 'no' }" )

            abstract = f"**{agent_name} Job Summary**\n\n" + "\n".join( summary_lines )
            message  = f"Here's what I have for your {agent_name} job. Does this look right?"

            response = self._ask_for_confirmation( message, user_email, abstract=abstract, context=context )

            if response is None:
                return None

            lower = response.lower().strip()

            # Plain "yes" or "no" (no comment)
            if lower == "yes":
                return args_dict

            if lower == "no":
                context.reason = BATCH_DECLINED
                return None

            # "yes [comment: ...]" or "no [comment: ...]"
            comment = self._extract_comment( response )

            if lower.startswith( "yes" ):
                if comment:
                    modification = self._parse_modification( comment, args_dict, spec )
                    if modification and modification.is_modify() and modification.arg_name and modification.new_value:
                        args_dict[ modification.arg_name ] = modification.new_value
                        if self.debug: print( f"  Modified: {modification.arg_name} = {modification.new_value}" )
                    # User said "yes" — proceed even if parse failed
                return args_dict

            if lower.startswith( "no" ):
                if comment:
                    modification = self._parse_modification( comment, args_dict, spec )
                    if modification and modification.is_modify() and modification.arg_name and modification.new_value:
                        args_dict[ modification.arg_name ] = modification.new_value
                        if self.debug: print( f"  Modified: {modification.arg_name} = {modification.new_value}" )
                        # Loop continues — re-present updated summary
                        continue
                # No comment or parse failed — respect the "no"
                context.reason = BATCH_DECLINED
                return None

        # Safety valve: too many iterations
        if self.debug: print( "[Expeditor] Max confirmation iterations reached, proceeding" )
        return args_dict

    def _parse_modification( self, user_response, args_dict, spec ):
        """
        Use LLM to parse a user's modification intent from their voice response.

        Requires:
            - user_response is a non-empty string
            - args_dict contains current arguments
            - spec is the agent's ArgSpec

        Ensures:
            - Returns ArgConfirmationResponse on successful parse
            - Returns None on parse failure

        Args:
            user_response: The user's voice response text
            args_dict: Current argument dictionary
            spec: ArgSpec for context

        Returns:
            ArgConfirmationResponse or None
        """
        try:
            template_raw = cu.get_file_as_string(
                cu.get_project_root() + self.confirmation_prompt_path
            )

            processor = PromptTemplateProcessor( debug=self.debug )
            template_processed = processor.process_template(
                template_raw, "argument confirmation"
            )

            # Build current args summary and arg names list
            system_args = set( spec.system_provided )
            current_args_str = ", ".join(
                f"{k}={v}" for k, v in args_dict.items()
                if k not in system_args and k != "no_confirm"
            )
            arg_names_str = ", ".join(
                k for k in args_dict.keys()
                if k not in system_args and k != "no_confirm"
            )

            # Also include fallback question keys as valid arg names
            fallback_keys = ", ".join( spec.fallback_questions.keys() )
            if fallback_keys:
                arg_names_str = arg_names_str + ", " + fallback_keys if arg_names_str else fallback_keys

            # Runtime scheduling args (universal across all agents)
            runtime_arg_names = "scheduled_at, monopolize"
            arg_names_str = arg_names_str + ", " + runtime_arg_names if arg_names_str else runtime_arg_names

            prompt = template_processed.format(
                user_response = user_response,
                current_args  = current_args_str,
                arg_names     = arg_names_str
            )

            if self.debug and self.verbose:
                print( f"[Expeditor] Confirmation prompt ({len( prompt )} chars):\n{prompt[ :300 ]}..." )

            llm_client = self.llm_factory.get_client(
                self.llm_spec_key, debug=self.debug, verbose=self.verbose
            )
            response = llm_client.run( prompt )

            if self.debug: print( f"[Expeditor] Confirmation LLM response: {response[ :200 ]}" )

            parsed = ArgConfirmationResponse.from_xml( response )
            return parsed

        except Exception as e:
            print( f"[Expeditor] Failed to parse confirmation response: {e}" )
            return None

    def _inject_system_args( self, args_dict, spec, user_email, session_id, user_id ):
        """
        Inject system-provided arguments into the args dictionary.

        Requires:
            - args_dict is a dict of user-provided arguments
            - spec has a "system_provided" list

        Ensures:
            - Returns args_dict with system args injected
            - Does not overwrite existing user-provided values

        Returns:
            dict: Args dict with system args added
        """
        system_map = {
            "user_email"  : user_email,
            "session_id"  : session_id,
            "user_id"     : user_id,
            "no_confirm"  : True,
        }

        for sys_arg in spec.system_provided:
            if sys_arg in system_map and sys_arg not in args_dict:
                args_dict[ sys_arg ] = system_map[ sys_arg ]

        return args_dict

    def _parse_lora_args( self, raw_args_str ):
        """
        Parse LORA raw argument string into a dictionary.

        Handles formats:
            - key="value"
            - key='value'
            - key=value (no quotes, stops at whitespace or comma)

        Requires:
            - raw_args_str is a string (may be empty or None)

        Ensures:
            - Returns dict mapping arg names to values
            - Handles multiple formats gracefully

        Args:
            raw_args_str: Raw argument string from LORA router

        Returns:
            dict: Parsed argument name-value pairs
        """
        if not raw_args_str or not raw_args_str.strip():
            return {}

        result = {}

        # Match key="value", key='value', or key=value patterns
        pattern = r'(\w+)\s*=\s*(?:"([^"]*?)"|\'([^\']*?)\'|(\S+))'
        matches = re.findall( pattern, raw_args_str )

        for match in matches:
            key = match[ 0 ]
            # Value is in whichever capture group matched
            value = match[ 1 ] or match[ 2 ] or match[ 3 ]
            result[ key ] = value

        return result

    def _resolve_default( self, command_key, arg_name, registry_default ):
        """
        Resolve default value for an argument: config override > registry > None.

        Requires:
            - command_key is a key in JOB_ARG_CONTRACTS
            - arg_name is the CLI argument name
            - registry_default is the fallback_defaults value (or None)

        Ensures:
            - Returns config override if present, else registry default, else None
            - A REQUIRED user arg is never looked up in config (row fb49da08).
              The "expeditor default value" key family covers optional args only
              — budget / audience / audience_context / languages. Asking it for a
              required arg like `query` or `prompt` always misses, and the miss
              is not silent: splain_me then prints
              "¿WUH? key [expeditor default value for research to podcast query]
              NOT found in splainer" on every single run. Adding a splainer entry
              would have documented a key that should never exist, so the fix is
              to stop asking. A required arg has no default by definition — that
              is what makes it required.

        Args:
            command_key: Routing command key (e.g., "agent router go to deep research")
            arg_name: CLI argument name (e.g., "budget")
            registry_default: Default from agent_registry fallback_defaults

        Returns:
            str or None: Resolved default value
        """
        entry = JOB_ARG_CONTRACTS.get( command_key )
        if entry is not None and arg_name in entry[ "required_user_args" ]:
            return registry_default

        agent_short = command_key.replace( "agent router go to ", "" )
        config_key  = f"expeditor default value for {agent_short} {arg_name}"
        config_value = self.config_mgr.get( config_key, default=None )
        if config_value is not None:
            return config_value
        return registry_default

    def _build_request_context( self, spec, command, original_question, final_args, missing_args ):
        """
        Build a markdown abstract summarizing the current request context.

        Displayed alongside batch question forms in the notification UI (not spoken via TTS).
        Helps the user understand why they're being asked and what the system already knows.

        Requires:
            - spec is the ArgSpec for command
            - command is the routing command key (used for the user-visible-args
              lookup — the spec is no longer identity-matchable against the
              registry, so the caller passes the key directly; the result is
              identical to the former reverse lookup by entry identity)
            - original_question is the user's voice command string
            - final_args is a dict of already-extracted arguments
            - missing_args is a list of arg names still needed

        Ensures:
            - Returns a markdown string with request context
            - Only includes user-visible args in "Already extracted" section
            - Conditionally includes sections only when non-empty

        Args:
            spec: ArgSpec for the target agent
            command: Routing command key for the user-visible-args lookup
            original_question: Full voice command transcription
            final_args: Dict of already-resolved arguments
            missing_args: List of arg names still needed

        Returns:
            str: Markdown-formatted context summary
        """
        display_name = self._resolve_display_name( spec )

        lines = [
            f'**Your request**: "{original_question}"',
            f"**Agent**: {display_name}",
        ]

        # Filter present args to user-visible only
        user_visible = get_user_visible_args( command )
        system_args  = set( spec.system_provided )

        visible_present = {
            k: v for k, v in final_args.items()
            if k not in system_args
            and k != "no_confirm"
            and ( user_visible is None or k in user_visible )
        }

        if visible_present:
            lines.append( "" )
            lines.append( "**Already extracted**:" )
            for k, v in visible_present.items():
                lines.append( f"- {k}: {v}" )

        if missing_args:
            lines.append( "" )
            lines.append( "**Still needed**: " + ", ".join( missing_args ) )

        return "\n".join( lines )

    def _ask_for_arg( self, arg_name, question, user_email, response_default=None, abstract=None,
                      card_id=None, *, context=None ):
        """
        Ask the user for a missing argument via synchronous notification.

        Requires:
            - arg_name is a non-empty string
            - question is the question text to ask
            - user_email is the target user's email

        Ensures:
            - Returns user's response string on success
            - Returns None on timeout, error, or cancellation

        Args:
            arg_name: Name of the missing argument
            question: Fallback question from registry
            user_email: Target user for notification
            response_default: Optional pre-filled default value for the input
            abstract: Optional markdown context shown in UI but not spoken
            context: THIS call's ExpediteContext (see ExpediteContext)

        Returns:
            str or None: User's response or None
        """
        context = context if context is not None else ExpediteContext()

        # An OPEN_ENDED ask carries no options, so response_options exists here ONLY to
        # name the ask — and it is omitted entirely when there is nothing to name, so
        # every other caller of this method sends exactly the envelope it always sent.
        # The arg rides with the id because two agents ask this same ask for different
        # arguments; the id says WHICH ASK, arg_name says WHICH FIELD.
        response_options = None
        if card_id is not None:
            response_options = { "card_id": card_id, "arg_name": arg_name }

        request = NotificationRequest(
            message          = question,
            response_type    = ResponseType.OPEN_ENDED,
            priority         = NotificationPriority.HIGH,
            target_user      = user_email,
            timeout_seconds  = 180,
            sender_id        = self.SENDER_ID,
            title            = f"Missing: {arg_name}",
            suppress_ding    = False,
            response_default = response_default,
            abstract         = abstract,
            job_id           = context.job_id,
            response_options = response_options
        )

        response = notify_user_sync( request=request, debug=self.debug, bearer_token=context.bearer_token )
        context.notification_status = response.status

        if self.debug:
            print( f"[Expeditor] _ask_for_arg response: success={response.success}, status={response.status}, "
                   f"exit_code={response.exit_code}, is_timeout={response.is_timeout}, "
                   f"value={response.response_value[ :100 ] if response.response_value else None}" )

        if response.success and response.response_value:
            value = response.response_value.strip()
            # Check for cancellation keywords — the ONE outcome that is a user decision
            if value.lower() in ( "cancel", "nevermind", "never mind", "stop", "quit" ):
                context.reason = BATCH_DECLINED
                return None
            return value

        # No usable answer — a machine failure, never a user cancellation (bug 68198c9f)
        context.reason = self._classify_ask_failure( response )
        return None

    def _ask_choice_for_arg( self, arg_name, question, options, user_email, abstract=None,
                             card_id=None, *, context=None ):
        """
        Ask the user to pick a value for a missing arg from a fixed list, using the
        SAME multiple-choice card the routing confirm uses — no new card, renderer,
        or response shape. The request envelope is copied from
        todo_fifo_queue._confirm_agentic_routing (MULTIPLE_CHOICE +
        response_options={"questions":[…]}); the JSON answer parsing is copied from
        the same site. Transport params (sender, timeout, token, job) follow the
        sibling _ask_for_arg so the two asks behave identically.

        Requires:
            - arg_name is a non-empty string (used verbatim as the answer header)
            - question is the prompt text (spoken + shown)
            - options is a non-empty list of { "label": str, "description": str };
              labels are unique and are the ONLY values the user can return
            - user_email is the target user's email

        Ensures:
            - Returns the chosen option's label on a pick
            - Returns None on Cancel, timeout, or delivery/parse failure (the
              failure reason is recorded on context.reason)
            - Returns DOC_CHOICE_DESCRIBE_SENTINEL when the user picks the
              "Let me describe it instead" escape
            - Never returns a value the caller did not put in `options`

        Args:
            arg_name: name of the missing argument (also the answer header)
            question: the question text
            options: list of { "label", "description" } choices (the caller adds
                     any Describe/Cancel escapes)
            user_email: target user for the notification
            abstract: optional markdown context shown in UI, not spoken

        Returns:
            str or None: chosen label, DOC_CHOICE_DESCRIBE_SENTINEL, or None
        """
        context = context if context is not None else ExpediteContext()
        response_options = {
            "questions": [ {
                "question"     : question,
                "header"       : arg_name,
                "multi_select" : False,
                "options"      : options
            } ]
        }
        # The id rides BESIDE questions, not inside one: it names the card, not a
        # question on it. Omitted entirely when the caller does not name one, so the
        # routing-confirm card and every other user of this ask are byte-identical to
        # what they sent before.
        if card_id is not None:
            response_options[ "card_id" ]  = card_id
            # The arg rides WITH the id, on both ask surfaces. The id says which ask;
            # two agents ask the same one for different arguments (podcast's
            # `research`, presentation's `source`), and the matcher narrows on this.
            # Sending it from only one surface would leave that filter half-real —
            # code with no producer, exercised only by synthetic tests (María).
            response_options[ "arg_name" ] = arg_name

        request = NotificationRequest(
            message          = question,
            response_type    = ResponseType.MULTIPLE_CHOICE,
            priority         = NotificationPriority.HIGH,
            target_user      = user_email,
            timeout_seconds  = 180,
            sender_id        = self.SENDER_ID,
            title            = f"Missing: {arg_name}",
            suppress_ding    = False,
            abstract         = abstract,
            job_id           = context.job_id,
            response_options = response_options
        )

        response = notify_user_sync( request=request, debug=self.debug, bearer_token=context.bearer_token )
        context.notification_status = response.status

        if not ( response.success and response.response_value ):
            # Delivery/timeout/parse failure — a machine failure, never a user choice.
            context.reason = self._classify_ask_failure( response )
            return None

        # MULTIPLE_CHOICE returns the raw label OR JSON { "answers": { <header>: label } }.
        # Parsing copied verbatim in shape from todo_fifo_queue.py:1069-1077.
        selected = response.response_value.strip()
        if selected.startswith( "{" ):
            try:
                answers  = json.loads( selected ).get( "answers", {} )
                selected = answers.get( arg_name, answers.get( "0", selected ) )
            except ( json.JSONDecodeError, AttributeError ):
                pass  # fall through with the raw value

        if selected is None or selected == DOC_CHOICE_CANCEL_LABEL:
            context.reason = BATCH_DECLINED
            return None
        if selected == DOC_CHOICE_DESCRIBE_LABEL:
            return DOC_CHOICE_DESCRIBE_SENTINEL
        return selected

    def _describe_candidate( self, rel_path ):
        """
        Human hint for a candidate document: its folder, plus a yyyy.mm.dd date
        parsed from the filename prefix when present. Cosmetic only — the label
        carries the identity.

        Requires:
            - rel_path is a non-empty relative path string

        Ensures:
            - Returns a non-empty description string ("<folder> · YYYY-MM-DD" when a
              date prefix is present, else "<folder>")
        """
        folder = os.path.dirname( rel_path ) or "."
        m = re.match( r"(\d{4})\.(\d{2})\.(\d{2})", os.path.basename( rel_path ) )
        return f"{folder} · {m.group( 1 )}-{m.group( 2 )}-{m.group( 3 )}" if m else folder

    @staticmethod
    def _document_choice_question( agent_display_name ):
        """
        The spoken question on the document choice card, in the calling agent's terms.

        ⚠️ THE PROXY ANSWER FILES MATCH ON THIS STRING. src/conf/notification-proxy-scripts/
        keys its entries by question_pattern, so changing the wording here without
        updating podcast.json / presentation.json makes an automated run hang at the
        card with nothing able to answer it.

        Requires:
            - agent_display_name is the registry display name, or None

        Ensures:
            - returns the podcast wording verbatim when the name is missing, so the
              podcast card is byte-identical to what it has always said
            - otherwise names the calling agent, lower-cased so it reads as prose

        Raises:
            - nothing
        """
        if not agent_display_name:
            return "Which document should I use for the podcast?"
        # "Podcast Generator" -> "podcast", "Presentation Generator" -> "presentation".
        # The trailing word is dropped for TWO reasons, and the first is the load-bearing
        # one: it makes the podcast card come out BYTE-IDENTICAL to the string it has
        # always said, so this fix changes nothing a podcast user sees. It also reads
        # better — "for the presentation" is how a person would ask.
        subject = agent_display_name.lower()
        if subject.endswith( " generator" ):
            subject = subject[ : -len( " generator" ) ]
        return f"Which document should I use for the {subject}?"


    def _choose_document_from_matches( self, matches, docs_map, user_email,
                                       arg_name="research", agent_display_name=None, *, context=None ):
        """
        Present 2..MAX_CHOICE_OPTIONS candidate documents as the standard choice
        card and map the pick back to an absolute path. The doc-choice surface every
        fuzzy_file_match consumer uses, once the podcast fence came off (row 5bc22180).

        THE CARD SPEAKS AS THE CALLING AGENT. It used to hardcode the arg name
        "research" and the question "Which document should I use for the podcast?",
        which was invisible while podcast was the only consumer. Row 5bc22180 gave
        presentation the card, and the hardcoding immediately became a presentation
        user being asked about the podcast under a card titled "Missing: research" —
        the same defect row ea184d06 fixed on the OTHER two asks and never reached
        here. The defaults keep podcast's wording verbatim, so its card does not move.

        Requires:
            - matches is a list of relative-path keys into docs_map (caller has
              already enforced 2..MAX_CHOICE_OPTIONS)
            - docs_map maps relative_path -> absolute_path
            - user_email is the target user's email
            - arg_name is the calling agent's own argument name
            - agent_display_name is the calling agent's display name, or None to
              keep the podcast phrasing

        Ensures:
            - Returns the chosen candidate's ABSOLUTE path on a pick
            - Returns None on Cancel/timeout/failure
            - Returns DOC_CHOICE_DESCRIBE_SENTINEL when the user opts to describe
            - Never silently picks a file: a label outside the fixed option set
              returns None with BATCH_MALFORMED, not matches[0]

        Args:
            matches: relative-path candidate keys (2..MAX_CHOICE_OPTIONS)
            docs_map: relative_path -> absolute_path
            user_email: target user for the notification

        Returns:
            str or None: absolute path, DOC_CHOICE_DESCRIBE_SENTINEL, or None
        """
        context = context if context is not None else ExpediteContext()
        options      = []
        label_to_rel = {}
        for rel in matches:
            base  = os.path.basename( rel )
            label = base if base not in label_to_rel else rel   # basename collision → full rel path
            label_to_rel[ label ] = rel
            options.append( { "label": label, "description": self._describe_candidate( rel ) } )
        options.append( { "label": DOC_CHOICE_DESCRIBE_LABEL, "description": "None of these — let me describe it" } )
        options.append( { "label": DOC_CHOICE_CANCEL_LABEL,   "description": "Cancel this request" } )

        chosen = self._ask_choice_for_arg(
            arg_name,
            self._document_choice_question( agent_display_name ),
            options,
            user_email,
            card_id=DOCUMENT_CHOICE_CARD_ID,
            context=context
        )
        if chosen is None or chosen == DOC_CHOICE_DESCRIBE_SENTINEL:
            return chosen

        rel = label_to_rel.get( chosen )
        if rel is not None and rel in docs_map:
            return docs_map[ rel ]
        # A label outside the fixed option set — the card cannot produce this, so
        # treat it as a non-answer rather than guessing (kills the old first-match).
        context.reason = BATCH_MALFORMED
        return None

    def _ask_for_confirmation( self, message, user_email, abstract=None, *, context=None ):
        """
        Ask the user a YES_NO confirmation question via synchronous notification.

        Requires:
            - message is a non-empty string (spoken via TTS)
            - user_email is the target user's email

        Ensures:
            - Returns raw response string ("yes", "no", "yes [comment: ...]", "no [comment: ...]")
            - Returns None on timeout or error

        Args:
            message: The confirmation question to speak
            user_email: Target user for notification
            abstract: Optional markdown context shown in UI but not spoken

        Returns:
            str or None: Raw response string or None
        """
        context = context if context is not None else ExpediteContext()
        request = NotificationRequest(
            message          = message,
            response_type    = ResponseType.YES_NO,
            priority         = NotificationPriority.HIGH,
            target_user      = user_email,
            timeout_seconds  = 180,
            sender_id        = self.SENDER_ID,
            title            = "Confirm",
            suppress_ding    = False,
            response_default = "no",
            abstract         = abstract,
            job_id           = context.job_id
        )

        response = notify_user_sync( request=request, debug=self.debug, bearer_token=context.bearer_token )
        context.notification_status = response.status

        if self.debug:
            print( f"[Expeditor] _ask_for_confirmation response: success={response.success}, status={response.status}, "
                   f"exit_code={response.exit_code}, is_timeout={response.is_timeout}, "
                   f"value={response.response_value[ :100 ] if response.response_value else None}" )

        if response.success and response.response_value:
            return response.response_value.strip()

        # Confirmation never got a usable answer — a machine failure, not a decline
        # (bug 68198c9f). The measured stage-killer: an undeliverable confirm.
        context.reason = self._classify_ask_failure( response )
        return None

    @staticmethod
    def _extract_comment( response_text ):
        """
        Extract comment text from a YES_NO response with annotation.

        Requires:
            - response_text is a string like "yes [comment: change budget to 10]"

        Ensures:
            - Returns the comment string if pattern matches
            - Returns None if no comment found

        Args:
            response_text: Raw YES_NO response string

        Returns:
            str or None: Extracted comment text or None
        """
        match = re.search( r'\[comment:\s*(.+?)\]', response_text )
        return match.group( 1 ).strip() if match else None

    def _batch_collect_args( self, batchable_args, fallback_questions, user_email, fallback_defaults=None, command_key=None, abstract=None, *, context=None ):
        """
        Collect multiple missing arguments in a single batch notification.

        Sends all questions at once via OPEN_ENDED_BATCH notification type.
        User sees all questions on one screen and submits all answers together.
        When defaults are available, text inputs are pre-filled so the user
        can accept by simply hitting Submit All.

        Requires:
            - batchable_args is a list of arg names (len > 1)
            - fallback_questions maps arg names to question strings
            - user_email is the target user's email

        Ensures:
            - Returns ``( answers, reason )`` — ALWAYS a 2-tuple, never a bare value
            - answers is a dict of { arg_name: value } with reason BATCH_ANSWERED,
              or None with one of BATCH_DECLINED / BATCH_UNREACHABLE /
              BATCH_MALFORMED / BATCH_INCOMPLETE
            - Questions include default_value when resolved default is not None

        ⚠️ THE REASON IS THE POINT (bug 2aaab1bf). This used to return a bare
        ``None`` for five structurally different outcomes, and its docstring said
        so out loud: "Returns None on timeout, error, or cancellation" — three
        meanings, one value. The caller could not tell them apart, so it printed
        "User cancelled batch collection" for all of them. A 503 (the prompt could
        not be delivered, so the user was never asked) killed the job as
        "cancelled by user". Only BATCH_DECLINED is a human decision; treating any
        other reason as one asserts an intent the user never expressed.

        Args:
            batchable_args: List of arg names to collect
            fallback_questions: Dict mapping arg names to question strings
            user_email: Target user for notification
            fallback_defaults: Optional dict mapping arg names to default values
            command_key: Optional routing command key for config override lookup
            abstract: Optional markdown context shown in UI but not spoken

        Returns:
            ( dict, str ) | ( None, str ): the collected answers with
            BATCH_ANSWERED, or None with the BATCH_* reason it failed.
        """
        context = context if context is not None else ExpediteContext()
        if fallback_defaults is None:
            fallback_defaults = {}

        questions = []
        for arg_name in batchable_args:
            question_text = fallback_questions.get(
                arg_name, f"Please provide the '{arg_name}' argument."
            )
            q = {
                "question" : question_text,
                "header"   : arg_name
            }
            # Resolve default: config override > registry > None
            resolved_default = self._resolve_default(
                command_key, arg_name, fallback_defaults.get( arg_name )
            ) if command_key else fallback_defaults.get( arg_name )
            if resolved_default is not None:
                q[ "default_value" ] = resolved_default
            questions.append( q )

        tts_message      = format_open_ended_batch_for_tts( questions )
        response_options = convert_open_ended_batch_for_api( questions )

        request = NotificationRequest(
            message          = tts_message,
            response_type    = ResponseType.OPEN_ENDED_BATCH,
            priority         = NotificationPriority.HIGH,
            target_user      = user_email,
            timeout_seconds  = 300,
            sender_id        = self.SENDER_ID,
            title            = "Missing arguments",
            response_options = response_options,
            suppress_ding    = False,
            abstract         = abstract,
            job_id           = context.job_id
        )

        response = notify_user_sync( request=request, debug=self.debug, bearer_token=context.bearer_token )
        context.notification_status = response.status

        if self.debug:
            print( f"[Expeditor] _batch_collect_args response: success={response.success}, status={response.status}, "
                   f"exit_code={response.exit_code}, is_timeout={response.is_timeout}, "
                   f"value={response.response_value[ :100 ] if response.response_value else None}" )

        if not response.success or not response.response_value:
            # The user was NEVER (effectively) ASKED. Two distinct machine failures,
            # neither a user decision (bugs 2aaab1bf, 68198c9f): a timeout means the
            # budget elapsed with no answer; anything else means the prompt could not
            # be delivered (503 when no websocket is registered). Rick reads different
            # words for each on stage, so they must not collapse into one reason.
            reason = BATCH_TIMEOUT if response.is_timeout else BATCH_UNREACHABLE
            return None, reason

        # Parse JSON response
        try:
            parsed = json.loads( response.response_value )
        except ( json.JSONDecodeError, TypeError ):
            if self.debug: print( f"[Expeditor] Failed to parse batch response: {response.response_value}" )
            return None, BATCH_MALFORMED

        # Check for cancellation — a REAL user decision
        if parsed.get( "cancelled" ):
            return None, BATCH_DECLINED

        answers = parsed.get( "answers", {} )
        if not answers:
            return None, BATCH_MALFORMED

        # Check for cancellation keywords in any answer
        for arg_name, value in answers.items():
            if isinstance( value, str ) and value.lower().strip() in ( "cancel", "nevermind", "never mind", "stop", "quit" ):
                return None, BATCH_DECLINED

        # Check all requested args have non-empty values
        for arg_name in batchable_args:
            if arg_name not in answers or not str( answers.get( arg_name, "" ) ).strip():
                if self.debug: print( f"[Expeditor] Batch response missing arg: {arg_name}" )
                return None, BATCH_INCOMPLETE

        return answers, BATCH_ANSWERED

    def _handle_fuzzy_file_match( self, user_email, agent_display_name=None, original_question=None, use_choice_card=False, arg_name="research", ask_question=None, file_arg=None, *, context=None ):
        """
        Use fuzzy file matching to find a document by user description.

        Searches the user's deep research directory AND additional directories
        from the agent-specific source search paths config key, falling back
        to 'podcast generator source search paths'.

        Auto-resolve (row bd0ce120): when the user already named the document in
        their original request, resolve THAT without a prompt — but ONLY skip the
        "which document?" ask when it lands on exactly one file. Zero or 2+ matches
        fall through to the interactive ask, exactly as before. The chosen file is
        NAMED to the user downstream (the confirmation summary; C's grace window),
        so a wrong auto-resolve is always visible and vetoable — never silent.

        Requires:
            - user_email is a valid email

        Ensures:
            - Returns full file path if user selects a match, or if original_question
              auto-resolves to exactly one file
            - Returns None if no matches found or user cancels

        Args:
            user_email: User's email (determines research directory)
            agent_display_name: Agent name for agent-specific search paths
            original_question: The user's original voice command; when it resolves to
                exactly one file, the document prompt is skipped (auto-resolve)
            arg_name: The argument being resolved, used as the prompt card's title
                ("Missing: <arg_name>"). Defaults to "research" — the podcast
                field — so existing callers are unchanged.
            ask_question: The agent's own wording for the "which document?" ask,
                normally the registry's fallback_questions entry for arg_name.
                None falls back to the podcast phrasing (row ea184d06: this used
                to be hardcoded, so a presentation job asked about "the podcast").
            file_arg: the argument's own typed declaration from the registry
                ({ kind, search_roots, search_paths_key }) — row a1420538. It says
                WHERE this argument's files live. None keeps the shared default
                roots and the podcast config key, which is what every caller got
                before any argument declared anything.

        Returns:
            str or None: Full path to selected document
        """
        context = context if context is not None else ExpediteContext()
        from cosa.agents.io_models.xml_models import FuzzyFileMatchResponse
        from cosa.config.configuration_manager import ConfigurationManager

        config_mgr   = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        project_root = cu.get_project_root()

        # Build docs_map: { relative_path → abs_path } from the argument's OWN roots
        # (row a1420538). The two per-user directories and the four extensions used to
        # be written into this method, so "where a file argument lives" was a property
        # of the expeditor rather than of the argument. They come from the declaration
        # now; an argument that declares nothing gets the same defaults, so a
        # not-yet-migrated caller searches exactly what it searched before.
        declaration = file_arg or {}
        search_roots = declaration.get( "search_roots" ) or DEFAULT_FILE_SEARCH_ROOTS
        docs_map     = {}

        for root in search_roots:
            rel_root   = root[ "path" ].format( user_email=user_email )
            extensions = tuple( root.get( "extensions" ) or DEFAULT_FILE_EXTENSIONS )
            abs_root   = f"{project_root}/{rel_root}"
            if not os.path.exists( abs_root ):
                continue
            for f in os.listdir( abs_root ):
                if f.endswith( extensions ):
                    docs_map[ f"{rel_root}/{f}" ] = f"{abs_root}/{f}"

        # Extra directories from config, walked recursively. THE KEY IS DECLARED, not
        # derived: it used to be built from the display name — "presentation generator
        # source search paths" — and fell back to the PODCAST's key when that one was
        # absent, so an agent with no key of its own silently searched wherever the
        # podcast was configured to look.
        search_paths_key = declaration.get( "search_paths_key" ) or "podcast generator source search paths"
        search_paths_raw = config_mgr.get( search_paths_key, default="/src" )
        if self.debug: print( f"[Expeditor] Extra search paths from {search_paths_key!r}" )
        search_dirs = [ d.strip() for d in search_paths_raw.split( "," ) if d.strip() ]
        source_extensions = DEFAULT_FILE_EXTENSIONS

        for search_dir in search_dirs:
            abs_search_dir = project_root + search_dir
            if not os.path.exists( abs_search_dir ):
                if self.debug: print( f"[Expeditor] Search dir not found: {abs_search_dir}" )
                continue
            for root, _dirs, files in os.walk( abs_search_dir ):
                for f in files:
                    if f.endswith( source_extensions ):
                        abs_path = os.path.join( root, f )
                        rel_path = os.path.relpath( abs_path, project_root )
                        if rel_path not in docs_map:
                            docs_map[ rel_path ] = abs_path

        if not docs_map:
            if self.debug: print( f"[Expeditor] No source files found in any search directory" )
            return self._ask_for_arg(
                arg_name,
                "No documents found. Please provide the path to a document.",
                user_email,
                context=context
            )

        # ── Auto-resolve (row bd0ce120) ──────────────────────────────────────
        # Rick already named the document in his original request; try to resolve
        # THAT with no prompt. Skip the "which document?" ask ONLY on an exactly-
        # one-file resolve — 0 or 2+ falls through to the interactive ask below,
        # exactly as before. A wrong pick is NOT silent: the resolved file is named
        # to the user by the _confirm_and_iterate summary (Step 8), which gates on a
        # yes/no before submission — that summary is the veto surface today.
        # card_shown gates the choice card to AT MOST ONCE per call: after a
        # "describe instead" (or a first typed description), a second ambiguity
        # falls to the exact-path ask, never back to the card — otherwise the
        # card→describe→ask cycle would only exit on Cancel.
        card_shown = False

        if original_question:
            auto_status, auto_matches = self._match_description_to_files(
                original_question, docs_map, config_mgr, project_root
            )
            if auto_status in ( "exact", "fuzzy" ) and len( auto_matches ) == 1:
                resolved = docs_map[ auto_matches[ 0 ] ]
                if self.debug: print( f"[Expeditor] Auto-resolved research from original request → {resolved}" )
                return resolved
            # 2..cap candidates on the FIRST turn → the standard choice card (opt-in
            # per caller — podcast only). A pick returns the path; Cancel returns
            # None; "describe instead" falls through to the open ask below.
            if use_choice_card and auto_status in ( "exact", "fuzzy" ) and 2 <= len( auto_matches ) <= MAX_CHOICE_OPTIONS:
                if self.debug: print( f"[Expeditor] {len( auto_matches )} first-turn matches — showing choice card" )
                chosen     = self._choose_document_from_matches(
                    auto_matches, docs_map, user_email,
                    arg_name=arg_name, agent_display_name=agent_display_name,
                    context=context
                )
                card_shown = True
                if chosen != DOC_CHOICE_DESCRIBE_SENTINEL:
                    return chosen   # abs path, or None on Cancel/failure
            if self.debug: print( f"[Expeditor] No single-file auto-resolve (status={auto_status}, matches={len( auto_matches )}) — asking" )

        # Ask user to describe which document. The wording comes from the calling
        # agent's registry entry — a presentation job must not ask about "the
        # podcast" (row ea184d06).
        description = self._ask_for_arg(
            arg_name,
            ask_question or "Which document should I use for the podcast? Describe it or say the filename.",
            user_email,
            card_id=DOCUMENT_DESCRIBE_ASK_ID,
            context=context
        )
        if not description:
            return None

        status, matches = self._match_description_to_files( description, docs_map, config_mgr, project_root )

        if status == "too_broad":
            # Candidate set too large to send whole + no keyword overlap — a capped
            # slice would be unranked. Ask for an exact path rather than guess.
            return self._ask_for_arg(
                arg_name,
                "I couldn't match that to a document. Please say the exact filename or path.",
                user_email,
                context=context
            )
        if status == "error":
            return self._ask_for_arg(
                arg_name,
                "Matching failed. Please provide the exact filename or path.",
                user_email,
                context=context
            )

        if not matches:
            if self.debug: print( "[Expeditor] No fuzzy matches found" )
            return self._ask_for_arg(
                arg_name,
                "I couldn't find a matching document. Please say the exact filename or path.",
                user_email,
                context=context
            )

        if len( matches ) == 1:
            return docs_map[ matches[ 0 ] ]

        # Multiple matches. Podcast (use_choice_card) shows the standard choice
        # card — but only if one has NOT already been shown this call, so a
        # post-describe ambiguity terminates at the exact-path ask instead of
        # looping back to the card. More than the UX cap also goes to the exact
        # ask. Because the card carries no free text to mis-parse, the old silent
        # first-match fallback below is unreachable on the podcast path.
        if use_choice_card:
            if not card_shown and len( matches ) <= MAX_CHOICE_OPTIONS:
                chosen = self._choose_document_from_matches(
                    matches, docs_map, user_email,
                    arg_name=arg_name, agent_display_name=agent_display_name,
                    context=context
                )
                if chosen != DOC_CHOICE_DESCRIBE_SENTINEL:
                    return chosen   # abs path, or None on Cancel/failure
            return self._ask_for_arg(
                arg_name,
                "Please say the exact filename or path of the document you want.",
                user_email,
                context=context
            )

        # Non-podcast consumers (e.g. presentation `source`) — same numbered prompt,
        # now titled with the caller's own arg name rather than always "research".
        options_str = ", ".join( f"{i + 1}. {m}" for i, m in enumerate( matches ) )
        pick = self._ask_for_arg(
            arg_name,
            f"I found multiple matches: {options_str}. Say the number or name of the one you want.",
            user_email,
            context=context
        )
        if not pick:
            return None

        # Try to match by number
        try:
            idx = int( pick.strip() ) - 1
            if 0 <= idx < len( matches ):
                return docs_map[ matches[ idx ] ]
        except ValueError:
            pass

        # Try to match by name
        for m in matches:
            if pick.lower().strip() in m.lower():
                return docs_map[ m ]

        # Fallback: use first match
        return docs_map[ matches[ 0 ] ]

    def _match_description_to_files( self, description, docs_map, config_mgr, project_root ):
        """
        Resolve a free-text description to candidate document paths — NO prompts.

        The shared matching core used by BOTH the auto-resolve pre-step and the
        interactive ask in _handle_fuzzy_file_match, so there is one matching
        behaviour instead of two. Never asks the user; pure resolution.

        Requires:
            - description is a non-empty string
            - docs_map maps relative_path -> absolute_path (non-empty)

        Ensures:
            - Returns a 2-tuple ( status, matches ):
                ( "exact",     [ rel_path ] )   deterministic hit (len 1): a rel-path/
                                                basename hit, OR a strictly-dominant
                                                keyword-overlap winner (row 8e70a34d)
                ( "fuzzy",     [ rel, ... ] )   LLM matches validated against docs_map (0+)
                ( "too_broad", [] )             candidate set too large + no keyword overlap
                ( "error",     [] )             LLM/parse failure
            - matches are relative-path keys into docs_map (caller maps to abs)
            - docs_map is NOT mutated (the keyword prefilter runs on a copy)

        Args:
            description: The text to resolve (original question, or a typed answer)
            docs_map: relative_path -> absolute_path candidate map
            config_mgr: ConfigurationManager for the fuzzy-match template + LLM spec
            project_root: absolute project root for template path resolution

        Returns:
            ( str, list ): ( status, matches )
        """
        from cosa.agents.io_models.xml_models import FuzzyFileMatchResponse

        # 1. Exact relative-path or bare-filename hit → deterministic single match
        if description in docs_map:
            return ( "exact", [ description ] )
        for rel_path in docs_map:
            if os.path.basename( rel_path ) == description:
                return ( "exact", [ rel_path ] )

        # 1b. Deterministic keyword-overlap winner → skip the nondeterministic
        #     phi-4 pick. When exactly one candidate dominates keyword overlap the
        #     description clearly names it; a top-score tie falls through to the LLM
        #     below, unchanged (row 8e70a34d).
        dominant = dominant_keyword_match( docs_map, description )
        if dominant is not None:
            if self.debug: print( f"[Expeditor] Dominant keyword match → deterministic resolve: {dominant!r}" )
            return ( "exact", [ dominant ] )

        # 2. Keyword prefilter before the LLM call (avoid phi-4 8k-context overflow).
        #    Runs on a COPY so the caller's docs_map is untouched.
        filtered_map, arbitrary = prefilter_docs_map_by_keywords( dict( docs_map ), description, debug=self.debug )
        if arbitrary:
            # Weak or lossy narrowing on a large set: no keyword overlap, a thin
            # single-keyword best match, or a truncated scored list — the shortlist
            # can't be trusted, so ask for an exact path (rows c143fd84 / 888711f0).
            if self.debug: print( "[Expeditor] Weak/lossy narrowing on a large candidate set — asking for an exact path" )
            return ( "too_broad", [] )

        # 3. LLM fuzzy match, validated against the filtered map
        try:
            template_path = config_mgr.get( "prompt template for fuzzy file matching" )
            template = cu.get_file_as_string( project_root + template_path )

            processor = PromptTemplateProcessor( debug=self.debug )
            template = processor.process_template( template, "fuzzy file matching" )

            file_list = "\n".join( f"- {rel}" for rel in sorted( filtered_map.keys() ) )
            prompt = template.format( description=description, file_list=file_list )

            llm_client = self.llm_factory.get_client(
                config_mgr.get( "llm spec key for fuzzy file matching" ),
                debug=self.debug, verbose=self.verbose
            )
            response = llm_client.run( prompt )

            parsed  = FuzzyFileMatchResponse.from_xml( response )
            raw_matches = parsed.get_matches_list()

            # Validate against filtered_map (match relative paths or bare filenames)
            matches = []
            for m in raw_matches:
                if m in filtered_map:
                    matches.append( m )
                else:
                    for rel_path in filtered_map:
                        if os.path.basename( rel_path ) == m:
                            matches.append( rel_path )
                            break

            return ( "fuzzy", matches )

        except Exception as e:
            print( f"[Expeditor] Fuzzy match error: {e}" )
            return ( "error", [] )

    def _handle_tfe_checkpoint_match( self, user_email, user_description=None, *, context=None ):
        """
        Fuzzy-match a user's natural-language description of a stalled TFE job
        to a resume target (job ID or plan doc path).

        Session 9056c113 doc 16 Phase 2. Reuses resume_resolver infrastructure
        (list_resume_candidates + fuzzy_match_candidates) from doc 15 Phase 2.

        Requires:
            - user_email is a valid email address (scopes candidate pool)

        Ensures:
            - Returns resolved job_id (or plan path) for the REST endpoint
            - Returns None if user cancels or no candidates exist
            - Never raises — errors fall through to _ask_for_arg fallback

        Args:
            user_email: User's email for candidate scoping
            user_description: Optional pre-captured description (else prompts via TTS)

        Returns:
            str or None: Resolved identifier for resume-from dispatch
        """
        context = context if context is not None else ExpediteContext()
        try:
            from cosa.agents.test_fix_expediter.resume_resolver import (
                list_resume_candidates, fuzzy_match_candidates,
            )

            candidates = list_resume_candidates( user_email )
            if not candidates:
                if self.debug: print( "[Expeditor] No TFE candidates found" )
                return self._ask_for_arg(
                    "resume_from",
                    "No stalled TFE jobs or recent plans found. Please provide a job ID (tfe-*) or paste a plan doc path.",
                    user_email,
                    context=context
                )

            if not user_description:
                user_description = self._ask_for_arg(
                    "resume_from",
                    f"Which TFE job would you like to resume? I found {len( candidates )} candidate(s). Describe the one you want.",
                    user_email,
                    context=context
                )
                if not user_description:
                    return None

            # Fast-path: if the description LOOKS like a job ID or plan path,
            # return it directly without invoking the LLM.
            s = user_description.strip()
            if s.startswith( "tfe-" ) or s.endswith( "-plan.md" ) or "/plans/" in s:
                if self.debug: print( f"[Expeditor] Fast-path match: {s[:60]}" )
                return s

            # LLM fuzzy match against candidate index
            matches = fuzzy_match_candidates( user_description, candidates, debug=self.debug )

            # Auto-accept if top match has high confidence AND is resumable (stalled)
            if matches and matches[ 0 ][ "confidence" ] >= 0.9 and matches[ 0 ].get( "status" ) == "stalled":
                if self.debug: print( f"[Expeditor] Auto-selected top match: {matches[ 0 ][ 'job_id' ]}" )
                return matches[ 0 ][ "job_id" ]

            if not matches:
                if self.debug: print( "[Expeditor] No fuzzy matches — asking user" )
                return self._ask_for_arg(
                    "resume_from",
                    "Couldn't match your description to any stalled TFE job. Please provide a job ID or paste a plan path.",
                    user_email,
                    context=context
                )

            # Multiple or low-confidence matches — ask user to disambiguate
            top_matches = matches[ :3 ]
            options_str = ", ".join(
                f"{i + 1}. {m[ 'job_id' ][ -8: ]} ({m.get( 'summary', '?' )[ :40 ]})"
                for i, m in enumerate( top_matches )
            )
            pick = self._ask_for_arg(
                "resume_from",
                f"Found {len( matches )} possible match(es). Say the number or the job ID: {options_str}",
                user_email,
                context=context
            )
            if not pick:
                return None

            # Numeric pick
            try:
                idx = int( pick.strip() ) - 1
                if 0 <= idx < len( top_matches ):
                    return top_matches[ idx ][ "job_id" ]
            except ValueError:
                pass

            # Partial ID match fallback
            pick_lower = pick.lower().strip()
            for m in top_matches:
                if pick_lower in m[ "job_id" ].lower():
                    return m[ "job_id" ]

            # Last resort — top match
            return top_matches[ 0 ][ "job_id" ]

        except Exception as e:
            if self.debug: print( f"[Expeditor] TFE checkpoint match error: {e}" )
            return self._ask_for_arg(
                "resume_from",
                "TFE resume matching failed. Please provide an exact job ID or plan path.",
                user_email,
                context=context
            )


# ============================================================================
# Smoke Test
# ============================================================================

def quick_smoke_test():
    """
    Quick smoke test for RuntimeArgumentExpeditor.

    Tests imports, arg parsing, registry lookup, and help capture.
    Does NOT require a running server or LLM.
    """
    cu.print_banner( "Runtime Argument Expeditor Smoke Test", prepend_nl=True )

    tests_passed = 0
    tests_failed = 0

    # Test 1: Imports
    print( "\n1. Testing imports..." )
    try:
        from cosa.agents.runtime_argument_expeditor.agent_registry import JOB_ARG_CONTRACTS, get_cli_help
        from cosa.agents.runtime_argument_expeditor.xml_models import ExpeditorResponse
        from cosa.agents.runtime_argument_expeditor.expeditor import RuntimeArgumentExpeditor
        print( "   ✓ All imports successful" )
        tests_passed += 1
    except Exception as e:
        print( f"   ✗ Import failed: {e}" )
        tests_failed += 1

    # Test 2: _parse_lora_args
    print( "\n2. Testing _parse_lora_args..." )
    try:
        # Create a minimal expeditor for testing parse method
        class MockConfig:
            def get( self, key, **kwargs ):
                return "test"
        expeditor = RuntimeArgumentExpeditor.__new__( RuntimeArgumentExpeditor )
        expeditor.debug = False

        # Test various formats
        result = expeditor._parse_lora_args( 'topic="quantum computing" budget=10' )
        assert result[ "topic" ] == "quantum computing", f"Expected 'quantum computing', got '{result.get( 'topic' )}'"
        assert result[ "budget" ] == "10"
        print( "   ✓ Double-quoted args parsed" )

        result = expeditor._parse_lora_args( "topic='AI safety'" )
        assert result[ "topic" ] == "AI safety"
        print( "   ✓ Single-quoted args parsed" )

        result = expeditor._parse_lora_args( "budget=50" )
        assert result[ "budget" ] == "50"
        print( "   ✓ Unquoted args parsed" )

        result = expeditor._parse_lora_args( "" )
        assert result == {}
        print( "   ✓ Empty string returns empty dict" )

        result = expeditor._parse_lora_args( None )
        assert result == {}
        print( "   ✓ None returns empty dict" )

        tests_passed += 1
    except Exception as e:
        print( f"   ✗ Failed: {e}" )
        tests_failed += 1

    # Test 3: Registry lookup
    print( "\n3. Testing registry lookup..." )
    try:
        entry = JOB_ARG_CONTRACTS.get( "agent router go to deep research" )
        assert entry is not None
        assert "query" in entry[ "required_user_args" ]
        print( "   ✓ Deep research registry entry found" )

        entry = JOB_ARG_CONTRACTS.get( "agent router go to podcast generator" )
        assert entry is not None
        assert "research" in entry[ "required_user_args" ]
        assert entry[ "special_handlers" ][ "research" ] == "fuzzy_file_match"
        print( "   ✓ Podcast generator registry entry found (with special handler)" )

        tests_passed += 1
    except Exception as e:
        print( f"   ✗ Failed: {e}" )
        tests_failed += 1

    # Test 4: CLI help capture
    print( "\n4. Testing CLI help capture..." )
    try:
        help_text = get_cli_help( "agent router go to deep research" )
        if help_text:
            print( f"   ✓ Deep research help captured ({len( help_text )} chars)" )
        else:
            print( "   ⚠ Help returned None (CLI module may not be runnable)" )

        help_none = get_cli_help( "nonexistent" )
        assert help_none is None
        print( "   ✓ Missing command returns None" )

        tests_passed += 1
    except Exception as e:
        print( f"   ✗ Failed: {e}" )
        tests_failed += 1

    # Test 5: ExpeditorResponse XML round-trip
    print( "\n5. Testing ExpeditorResponse XML round-trip..." )
    try:
        response = ExpeditorResponse(
            all_required_met = "false",
            args_present     = "query=test topic",
            args_missing     = "budget, audience"
        )

        assert not response.is_complete()
        assert response.get_missing_list() == [ "budget", "audience" ]
        assert response.get_present_dict() == { "query": "test topic" }

        xml = response.to_xml()
        parsed = ExpeditorResponse.from_xml( xml )
        assert parsed.all_required_met == "false"
        assert parsed.args_present == "query=test topic"
        print( "   ✓ XML round-trip works" )

        complete = ExpeditorResponse(
            all_required_met = "true",
            args_present     = "query=biodiversity",
            args_missing     = ""
        )
        assert complete.is_complete()
        assert complete.get_missing_list() == []
        print( "   ✓ Complete response detected correctly" )

        tests_passed += 1
    except Exception as e:
        print( f"   ✗ Failed: {e}" )
        tests_failed += 1

    # Summary
    print( f"\n{'=' * 60}" )
    print( f"Expeditor Smoke Test: {tests_passed} passed, {tests_failed} failed" )
    print( "=" * 60 )

    return tests_failed == 0


if __name__ == "__main__":
    success = quick_smoke_test()
    exit( 0 if success else 1 )
