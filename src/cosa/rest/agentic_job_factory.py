#!/usr/bin/env python3
"""
Shared factory for creating agentic jobs in CJ Flow (COSA Jobs Flow).

Extracted from TodoFifoQueue to enable both voice routing and REST endpoints
to create jobs identically. This eliminates duplicated job creation code.

Used by:
    - todo_fifo_queue.py (voice path via expeditor)
    - routers/deep_research.py (REST form submission)
    - routers/podcast_generator.py (REST form submission)
    - routers/deep_research_to_podcast.py (REST form submission)
    - routers/mock_job.py (expeditor test mode)
"""

import shlex

from typing import Optional

_SEMANTIC_NONE = { "default", "no limit", "none", "skip", "no", "" }


def _parse_optional_int( value, default=None ):
    """
    Safely parse a value to int, treating semantic strings as None.

    Requires:
        - value is a string, int, None, or other type

    Ensures:
        - Returns int if value is a valid numeric string or int
        - Returns default if value is None, empty, a semantic skip word, or unparseable
    """
    if not value or str( value ).strip().lower() in _SEMANTIC_NONE:
        return default
    try:
        return int( value )
    except ( ValueError, TypeError ):
        return default


def _parse_boolean( value, default=False ):
    """
    Safely parse a value to bool, treating semantic strings appropriately.

    Requires:
        - value is a string, bool, None, or other type

    Ensures:
        - Returns True for "yes", "true", "1", "enable", "enabled"
        - Returns False for all other strings including "no", "false", "0"
        - Returns default if value is None
        - Passes through bool values unchanged
    """
    if value is None: return default
    if isinstance( value, bool ): return value
    s = str( value ).lower().strip()
    return s in ( "yes", "true", "1", "enable", "enabled" )


def _parse_optional_boolean( value ):
    """
    Parse a tri-state boolean: True / False / None.

    Returns None for missing, empty, or semantic-none values (signals "use the
    INI default"). Returns bool for explicit True/False (signals "override the
    INI default for this run only").

    Args:
        value: bool, str, None, or other

    Returns:
        Optional[bool]: None if unset, True/False if explicitly set
    """
    if value is None: return None
    if isinstance( value, bool ): return value
    s = str( value ).strip().lower()
    if s in _SEMANTIC_NONE: return None
    if s in ( "yes", "true", "1", "enable", "enabled" ): return True
    if s in ( "false", "0", "disable", "disabled", "off" ): return False
    return None


def _parse_optional_float( value, default=None ):
    """
    Safely parse a value to float, treating semantic strings as None.

    Requires:
        - value is a string, float, int, None, or other type

    Ensures:
        - Returns float if value is a valid numeric string or number
        - Returns default if value is None, empty, a semantic skip word, or unparseable
    """
    if not value or str( value ).strip().lower() in _SEMANTIC_NONE:
        return default
    try:
        return float( value )
    except ( ValueError, TypeError ):
        return default


def create_agentic_job( command, args_dict, user_id, user_email, session_id, debug=False, verbose=False ):
    """
    Factory function to create the correct agentic job based on command.

    Requires:
        - command is a recognized agentic routing command string
        - args_dict contains the required arguments for the target job
        - user_id, user_email, session_id are non-empty strings

    Ensures:
        - Returns appropriate Job instance for the command
        - Returns None if command is unrecognized

    Args:
        command: Routing command key (e.g., "agent router go to deep research")
        args_dict: Complete argument dictionary
        user_id: System user ID
        user_email: User's email address
        session_id: WebSocket session ID
        debug: Enable debug output
        verbose: Enable verbose output

    Returns:
        AgenticJobBase subclass instance, or None
    """
    from cosa.agents.bug_fix_expediter.job              import BugFixExpediterJob
    from cosa.agents.claude_code.job                     import ClaudeCodeJob
    from cosa.agents.deep_research.job                   import DeepResearchJob
    from cosa.agents.deep_research_to_podcast.job        import DeepResearchToPodcastJob
    from cosa.agents.deep_research_to_presentation.job   import DeepResearchToPresentationJob
    from cosa.agents.podcast_generator.job               import PodcastGeneratorJob
    from cosa.agents.presentation_generator.job          import PresentationGeneratorJob
    from cosa.agents.swe_team.job                        import SweTeamJob
    from cosa.agents.test_fix_expediter.job              import TestFixExpediterJob
    from cosa.agents.test_suite.job                      import TestSuiteJob
    from cosa.agents.heartbeat_poker_job                 import HeartbeatPokerJob, RecipientSpec
    from cosa.agents.heartbeat_poker_commons_gateway     import LupinCommonsGateway

    if command == "agent router go to deep research":
        job = DeepResearchJob(
            query              = args_dict.get( "query", "" ),
            user_id            = user_id,
            user_email         = user_email,
            session_id         = session_id,
            budget             = _parse_optional_float( args_dict.get( "budget" ) ),
            no_confirm         = True,
            dry_run            = _parse_boolean( args_dict.get( "dry_run" ) ),
            force_failure_mode = args_dict.get( "force_failure_mode" ),
            audience           = args_dict.get( "audience" ),
            audience_context   = args_dict.get( "audience_context" ),
            debug              = debug,
            verbose            = verbose
        )

    elif command == "agent router go to podcast generator":
        # Parse target_languages if provided as string
        languages = None
        if args_dict.get( "languages" ):
            if isinstance( args_dict[ "languages" ], list ):
                languages = args_dict[ "languages" ]
            else:
                languages = [ lang.strip() for lang in args_dict[ "languages" ].split( "," ) ]

        job = PodcastGeneratorJob(
            research_path      = args_dict.get( "research", "" ),
            user_id            = user_id,
            user_email         = user_email,
            session_id         = session_id,
            target_languages   = languages,
            dry_run            = _parse_boolean( args_dict.get( "dry_run" ) ),
            force_failure_mode = args_dict.get( "force_failure_mode" ),
            audience           = args_dict.get( "audience" ),
            audience_context   = args_dict.get( "audience_context" ),
            debug              = debug,
            verbose            = verbose
        )

    elif command == "agent router go to research to podcast":
        # Parse target_languages if provided as string
        languages = None
        if args_dict.get( "languages" ):
            if isinstance( args_dict[ "languages" ], list ):
                languages = args_dict[ "languages" ]
            else:
                languages = [ lang.strip() for lang in args_dict[ "languages" ].split( "," ) ]

        job = DeepResearchToPodcastJob(
            query            = args_dict.get( "query", "" ),
            user_id          = user_id,
            user_email       = user_email,
            session_id       = session_id,
            budget           = _parse_optional_float( args_dict.get( "budget" ) ),
            target_languages = languages,
            dry_run          = _parse_boolean( args_dict.get( "dry_run" ) ),
            audience         = args_dict.get( "audience" ),
            audience_context = args_dict.get( "audience_context" ),
            debug            = debug,
            verbose          = verbose
        )

    elif command == "agent router go to claude code":
        job = ClaudeCodeJob(
            prompt          = args_dict.get( "prompt", "" ),
            project         = args_dict.get( "project", "lupin" ),
            user_id         = user_id,
            user_email      = user_email,
            session_id      = session_id,
            task_type       = args_dict.get( "task_type", "BOUNDED" ),
            max_turns       = _parse_optional_int( args_dict.get( "max_turns" ) ),
            timeout_seconds = _parse_optional_int( args_dict.get( "timeout_seconds" ) ),
            dry_run         = _parse_boolean( args_dict.get( "dry_run" ) ),
            debug           = debug,
            verbose         = verbose
        )

    elif command == "agent router go to presentation generator":
        job = PresentationGeneratorJob(
            source_path             = args_dict.get( "source", "" ),
            user_id                 = user_id,
            user_email              = user_email,
            session_id              = session_id,
            target_duration_minutes = _parse_optional_int( args_dict.get( "target_duration_minutes" ) ),
            target_slide_count      = _parse_optional_int( args_dict.get( "target_slide_count" ) ),
            audience                = args_dict.get( "audience" ),
            audience_context        = args_dict.get( "audience_context" ),
            theme                   = args_dict.get( "theme" ),
            content_model           = args_dict.get( "content_model" ),
            render_only             = _parse_boolean( args_dict.get( "render_only" ) ),
            dry_run                 = _parse_boolean( args_dict.get( "dry_run" ) ),
            force_failure_mode      = args_dict.get( "force_failure_mode" ),
            debug                   = debug,
            verbose                 = verbose
        )

    elif command == "agent router go to research to presentation":
        job = DeepResearchToPresentationJob(
            query                   = args_dict.get( "query", "" ),
            user_id                 = user_id,
            user_email              = user_email,
            session_id              = session_id,
            budget                  = _parse_optional_float( args_dict.get( "budget" ) ),
            target_duration_minutes = _parse_optional_int( args_dict.get( "target_duration_minutes" ) ),
            target_slide_count      = _parse_optional_int( args_dict.get( "target_slide_count" ) ),
            theme                   = args_dict.get( "theme" ),
            lead_model              = args_dict.get( "lead_model" ),
            dry_run                 = _parse_boolean( args_dict.get( "dry_run" ) ),
            audience                = args_dict.get( "audience" ),
            audience_context        = args_dict.get( "audience_context" ),
            debug                   = debug,
            verbose                 = verbose,
        )

    elif command == "agent router go to swe team":
        job = SweTeamJob(
            task           = args_dict.get( "task", args_dict.get( "prompt", "" ) ),
            user_id        = user_id,
            user_email     = user_email,
            session_id     = session_id,
            dry_run        = _parse_boolean( args_dict.get( "dry_run" ) ),
            dry_run_phases = _parse_optional_int( args_dict.get( "dry_run_phases" ) ) or 10,
            dry_run_delay  = _parse_optional_float( args_dict.get( "dry_run_delay" ) ) or 1.5,
            lead_model     = args_dict.get( "lead_model" ),
            worker_model   = args_dict.get( "worker_model" ),
            budget         = _parse_optional_float( args_dict.get( "budget" ) ),
            timeout        = _parse_optional_int( args_dict.get( "timeout" ) ),
            trust_mode     = args_dict.get( "trust_mode" ),
            debug          = debug,
            verbose        = verbose
        )

    elif command == "agent router go to test suite":
        # Parse test_types: comma-separated string → list
        test_types_raw = args_dict.get( "test_types", "integration,e2e" )
        if isinstance( test_types_raw, str ):
            test_types = [ t.strip() for t in test_types_raw.split( "," ) if t.strip() ]
        else:
            test_types = test_types_raw

        # Parse pytest_args: JSON list or quote-aware string → list.
        # shlex.split, NOT str.split: a quoted expression like -k "a or b" must
        # survive as ONE -k value. The naive word-split shattered it — pytest
        # read the bare `or` as a file arg and exited 4, a silent zero-test run
        # that LOOKED submitted (2026-06-11, found independently by two sessions).
        pytest_args_raw = args_dict.get( "pytest_args", "" )
        if isinstance( pytest_args_raw, list ):
            pytest_args = pytest_args_raw
        elif pytest_args_raw and pytest_args_raw.lower() not in _SEMANTIC_NONE:
            try:
                pytest_args = shlex.split( pytest_args_raw )
            except ValueError as e:
                # Unbalanced quotes must fail LOUD at submit time — the silent
                # alternative is exactly the zero-test run this fix removes.
                raise ValueError( f"Malformed pytest_args {pytest_args_raw!r}: {e}" )
        else:
            pytest_args = []

        job = TestSuiteJob(
            test_types          = test_types,
            user_id             = user_id,
            user_email          = user_email,
            session_id          = session_id,
            pytest_args         = pytest_args,
            dry_run             = _parse_boolean( args_dict.get( "dry_run" ) ),
            auto_fix_on_failure = _parse_optional_boolean( args_dict.get( "auto_fix_on_failure" ) ),
            env_vars            = args_dict.get( "env_vars" ) or None,
            debug               = debug,
            verbose             = verbose
        )

    elif command == "agent router go to bug fix expediter":
        job = BugFixExpediterJob(
            dead_job_id           = args_dict.get( "dead_job_id", "" ),
            user_id               = user_id,
            user_email            = user_email,
            session_id            = session_id,
            extra_context         = args_dict.get( "extra_context", "" ),
            dry_run               = _parse_boolean( args_dict.get( "dry_run" ) ),
            lead_model_override   = args_dict.get( "lead_model_override" )   or None,
            worker_model_override = args_dict.get( "worker_model_override" ) or None,
            thinking_effort       = args_dict.get( "thinking_effort" )       or None,
            debug                 = debug,
            verbose               = verbose
        )

    elif command == "agent router go to test fix expediter":
        # Parse optional original_test_types / original_pytest_args (comma-separated)
        test_types_arg = args_dict.get( "original_test_types", [] )
        if isinstance( test_types_arg, str ):
            test_types_arg = [ s.strip() for s in test_types_arg.split( "," ) if s.strip() ]
        pytest_args_arg = args_dict.get( "original_pytest_args", [] )
        if isinstance( pytest_args_arg, str ):
            pytest_args_arg = [ s.strip() for s in pytest_args_arg.split( " " ) if s.strip() ]

        job = TestFixExpediterJob(
            remediation_snapshot_path = args_dict.get( "remediation_snapshot_path", "" ),
            source_test_suite_job_id  = args_dict.get( "source_test_suite_job_id", "" ),
            user_id                   = user_id,
            user_email                = user_email,
            session_id                = session_id,
            original_test_types       = test_types_arg,
            original_pytest_args      = pytest_args_arg,
            dry_run                   = _parse_boolean( args_dict.get( "dry_run" ) ),
            lead_model_override       = args_dict.get( "lead_model_override" )   or None,
            worker_model_override     = args_dict.get( "worker_model_override" ) or None,
            thinking_effort           = args_dict.get( "thinking_effort" )       or None,
            debug                     = debug,
            verbose                   = verbose,
        )

    elif command == "agent router go to test fix expediter resume":
        # Voice resume — mirrors POST /api/test-fix-expediter/resume-from
        # (queues.py:1857). resume_from is already fuzzy-matched by the expeditor's
        # tfe_checkpoint_match handler; resolve it to a single stalled job, then
        # rebuild via resume_job(). No single match (not-found / still-ambiguous) →
        # return None so the flow routes to the receptionist to speak the failure
        # (the voice path has no HTTP channel for a 404/ambiguous response).
        from cosa.agents.test_fix_expediter.resume_resolver import resolve_resume_target
        target = resolve_resume_target( args_dict.get( "resume_from", "" ), user_email )
        if target.job_id is None:
            return None
        overrides = {
            "lead_model_override"   : args_dict.get( "lead_model_override" ),
            "worker_model_override" : args_dict.get( "worker_model_override" ),
            "thinking_effort"       : args_dict.get( "thinking_effort" ),
        }
        overrides = { k: v for k, v in overrides.items() if v is not None }
        # resume_job() returns a fully-formed job carrying its ORIGINAL routing_command
        # and args from job_history; return it directly rather than falling through to
        # the common tail, which would overwrite those with the resume args.
        return resume_job( target.job_id, args_overrides=overrides or None )

    elif command == "agent router go to heartbeat poker":
        # recipients: list of {identifier, identifier_type, role} dicts → RecipientSpec list
        recipients = [
            RecipientSpec(
                identifier      = r[ "identifier" ],
                identifier_type = r.get( "identifier_type", "persona" ),
                role            = r[ "role" ],
            )
            for r in ( args_dict.get( "recipients" ) or [] )
        ]

        # termination_signal_kinds: list, or comma-separated string
        kinds_raw = args_dict.get( "termination_signal_kinds", "" )
        if isinstance( kinds_raw, list ):
            termination_signal_kinds = kinds_raw
        else:
            termination_signal_kinds = [ k.strip() for k in str( kinds_raw ).split( "," ) if k.strip() ]

        job = HeartbeatPokerJob(
            recipients                = recipients,
            cadence_seconds           = _parse_optional_int( args_dict.get( "cadence_seconds" ) ) or 180,
            termination_topic         = args_dict.get( "termination_topic", "" ),
            termination_signal_kinds  = termination_signal_kinds,
            workstream_id             = args_dict.get( "workstream_id", "" ),
            commons                   = LupinCommonsGateway.from_environment( sender_session_id=session_id ),
            deadman_consecutive_pokes = _parse_optional_int( args_dict.get( "deadman_consecutive_pokes" ) ) or 3,
            max_duration_seconds      = _parse_optional_int( args_dict.get( "max_duration_seconds" ) ) or 43_200,
            scheduled_at              = args_dict.get( "scheduled_at" ),
            monopolize                = _parse_boolean( args_dict.get( "monopolize" ) ),
            user_id                   = user_id,
            user_email                = user_email,
            session_id                = session_id,
            debug                     = debug,
            verbose                   = verbose,
        )

    else:
        print( f"[agentic_job_factory] Unknown command: {command}" )
        return None

    # Populate CJ Flow persistence fields on every constructed job so job_history
    # persists both the routing command and the exact args_dict the job was built from.
    # BFE's resubmit path reads these to reconstruct the original job faithfully.
    job.routing_command = command
    job.original_args   = dict( args_dict )
    return job


def resume_job( job_id_hash, config_mgr=None, args_overrides=None ):
    """
    Reconstruct a stalled job from its checkpoint and original args.

    Reads the checkpoint and original submission args from job_history,
    reconstructs the job via the normal factory path, and attaches the
    checkpoint for the orchestrator to load on execution.

    Requires:
        - job_id_hash references a stalled job with checkpoint data in DB
        - args_overrides is None or a dict of keys to merge into original_args

    Ensures:
        - Returns a fully constructed job with _resume_checkpoint attached
        - Returns None if job cannot be resumed (not found, not stalled, etc.)
        - Overrides with value None are ignored (preserve original_args entry);
          any non-None override replaces the corresponding key
    """
    from cosa.rest.job_persistence import get_checkpoint_for_job, get_original_args_for_job

    checkpoint = get_checkpoint_for_job( job_id_hash )
    if not checkpoint:
        print( f"[agentic_job_factory] No checkpoint found for {job_id_hash}" )
        return None

    job_info = get_original_args_for_job( job_id_hash )
    if not job_info or not job_info.get( "routing_command" ):
        print( f"[agentic_job_factory] No original args found for {job_id_hash}" )
        return None

    # Merge args_overrides into original_args (None values skipped so the caller
    # can pass a model dump without clobbering existing keys).
    merged_args = dict( job_info[ "original_args" ] )
    if args_overrides:
        for k, v in args_overrides.items():
            if v is not None:
                merged_args[ k ] = v

    # Reconstruct via normal factory path. config_mgr is accepted as a parameter
    # for forward-compat but create_agentic_job does not (yet) take it — drop here.
    job = create_agentic_job(
        command    = job_info[ "routing_command" ],
        args_dict  = merged_args,
        user_id    = job_info[ "user_id" ],
        user_email = job_info[ "user_email" ],
        session_id = job_info[ "session_id" ],
    )

    if job is None:
        print( f"[agentic_job_factory] Factory returned None for {job_id_hash}" )
        return None

    # Attach checkpoint for _execute() to pick up
    job._resume_checkpoint = checkpoint
    job._resume_checkpoint[ "resume_count" ] = checkpoint.get( "resume_count", 0 ) + 1

    return job
