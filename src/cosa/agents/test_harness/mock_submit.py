"""
The mock-job command behind POST /api/v2/submit (rows 432511fd, a3c59f2d).

WHY THIS MODULE EXISTS. `/api/mock-job/submit` (door 14) retired to 410, and Rick chose to
keep what it did rather than lose it: the four test suites that call it (the 12-scenario
proxy suite, the swe-team proxy suite, the expeditor mock-job smoke, and the CJ Flow
pause/schedule e2e) have no other way to put a zero-cost job on the queue or to exercise the
RuntimeArgumentExpeditor without a real agent. So the behaviour moved here, unchanged, and is
reached as the command `agent router go to mock job` through `/api/v2/submit`.

TWO MODES, ONE COMMAND — the same two the door had, selected the same way:

  • PLAIN — no `voice_command`: build a `MockAgenticJob` (sleeps, emits progress, optionally
    fails) from the door's own argument names. The job's config comes back in
    `submit_details["config"]`, exactly the dict the door put in `config`.

  • EXPEDITOR TEST — `voice_command` given: keyword-match the voice command to a real
    agentic command, run the RuntimeArgumentExpeditor on it (which may interview the user
    through notifications, so it needs the caller's bearer token — carried by
    `cosa.rest.v2.request_context`), and build a DRY-RUN job of the matched command. An
    optional `force_failure_mode` makes that job land in the dead queue so the Phase 6
    auto-fix loop can be exercised. The resolution comes back in `submit_details` as
    `command`, `args_resolved`, `dry_run`, `force_failure_mode`, `notification_status`.
    A user who cancels or times out raises `SubmitRefused`, which the flow reports as
    status failed / route_reason `expeditor_cancelled` with the same details.

This module never touches HTTP: the flow runs a submit in a worker thread, so the blocking
expeditor call is fine here.
"""

import uuid

from typing import Literal, Optional

from pydantic import BaseModel, Field

from cosa.rest.v2.refusal import SubmitRefused

# The mock commands are test scaffolding; the keyword matcher must never pick one as the
# "real" agent a voice command is about ("mock job" would otherwise match any voice command
# containing both words).
MOCK_COMMAND = "agent router go to mock job"


class MockJobArgs( BaseModel ):
    """The arguments of `agent router go to mock job` — the door's request body, minus the
    three fields that travel top-level on /api/v2/submit (websocket_id, scheduled_at,
    monopolize)."""
    iterations_min      : int   = Field( 3, ge=1, le=20, description="Minimum iterations" )
    iterations_max      : int   = Field( 8, ge=1, le=20, description="Maximum iterations" )
    sleep_min           : float = Field( 1.0, ge=0.1, le=30.0, description="Minimum sleep seconds" )
    sleep_max           : float = Field( 5.0, ge=0.1, le=30.0, description="Maximum sleep seconds" )
    failure_probability : float = Field( 0.0, ge=0.0, le=1.0, description="Probability of failure (0-1)" )
    fixed_iterations    : Optional[ int ]   = Field( None, ge=1, le=20, description="Override random iterations" )
    fixed_sleep         : Optional[ float ] = Field( None, ge=0.1, le=30.0, description="Override random sleep" )
    description         : Optional[ str ]   = Field( None, max_length=100, description="Custom description for queue display" )
    voice_command       : Optional[ str ]   = Field( None, description="Test the expeditor: route this voice command through RuntimeArgumentExpeditor" )
    force_failure_mode  : Optional[ Literal[ "code_bug", "infra_timeout", "rate_limit" ] ] = Field(
        None,
        description="Force the spawned dry-run job to fail with this error category so it lands in the dead queue (Phase 6 repair loop). Only honoured with voice_command."
    )


def match_voice_command( voice_command, contracts ):
    """
    Find the agentic command a voice command is about, by keyword.

    Requires:
        - voice_command is a string
        - contracts is the JOB_ARG_CONTRACTS mapping

    Ensures:
        - returns the first contract key whose every keyword (the key minus
          "agent router go to ") appears in the voice command, skipping the mock command
        - else the specific-before-general partial matches: presentation+research,
          presentation, podcast+research, podcast, research
        - returns None when nothing matches
    """
    lowered = voice_command.lower()
    for command in contracts.keys():
        if command == MOCK_COMMAND: continue
        keywords = command.replace( "agent router go to ", "" ).split()
        if all( kw in lowered for kw in keywords ):
            return command

    # Order matters: the compound cases must come before the bare "research" one, or
    # "research and present it" would match deep research instead of research-to-presentation.
    if "presentation" in lowered and "research" in lowered: return "agent router go to research to presentation"
    if "presentation" in lowered:                          return "agent router go to presentation generator"
    if "podcast" in lowered and "research" in lowered:      return "agent router go to research to podcast"
    if "podcast" in lowered:                                return "agent router go to podcast generator"
    if "research" in lowered:                               return "agent router go to deep research"
    return None


def validate_ranges( args ):
    """
    Refuse an inverted min/max range.

    Requires:
        - args is a MockJobArgs

    Raises:
        - ValueError naming the inverted pair
    """
    if args.iterations_min > args.iterations_max:
        raise ValueError( "iterations_min cannot be greater than iterations_max" )
    if args.sleep_min > args.sleep_max:
        raise ValueError( "sleep_min cannot be greater than sleep_max" )


def build_plain_mock_job( args, user_id, user_email, session_id, debug=False, verbose=False ):
    """
    Build a MockAgenticJob from validated args.

    Requires:
        - args is a MockJobArgs whose ranges validate_ranges accepted

    Ensures:
        - returns the job with `submit_details = { "config": … }` carrying the door's config
          dict: iterations, sleep_seconds, will_fail, fail_at_iteration (None unless it will
          fail), and estimated_duration
    """
    from cosa.agents.test_harness.mock_job import MockAgenticJob

    job = MockAgenticJob(
        user_id             = user_id,
        user_email          = user_email or "mock@test.com",
        session_id          = session_id,
        iterations_range    = ( args.iterations_min, args.iterations_max ),
        sleep_range         = ( args.sleep_min, args.sleep_max ),
        failure_probability = args.failure_probability,
        fixed_iterations    = args.fixed_iterations,
        fixed_sleep         = args.fixed_sleep,
        description         = args.description,
        debug               = debug,
        verbose             = verbose
    )
    estimated_duration = job.iterations * job.sleep_seconds
    job.submit_details = { "config": {
        "iterations"         : job.iterations,
        "sleep_seconds"      : round( job.sleep_seconds, 2 ),
        "will_fail"          : job.will_fail,
        "fail_at_iteration"  : job.fail_at_iteration if job.will_fail else None,
        "estimated_duration" : f"{estimated_duration:.1f}s",
    } }
    return job


def build_expeditor_test_job( args, user_id, user_email, bearer_token, debug=True ):
    """
    Route a voice command through the expeditor and build a dry-run job of the matched command.

    Requires:
        - args is a MockJobArgs with voice_command set
        - bearer_token is the caller's JWT, or None (then the expeditor's notifications go
          out unauthenticated — the degraded case, never another user's credential)

    Ensures:
        - returns the dry-run job with `submit_details = { "config": {…} }` carrying
          command, voice_command, args_resolved (user_email / session_id / user_id /
          no_confirm elided), dry_run True and force_failure_mode
        - the job's own routing_command / original_args are those of the MATCHED command,
          not of the mock command, so job_history describes the job that actually runs

    Raises:
        - ValueError when the voice command matches no agentic command
        - SubmitRefused( route_reason="expeditor_cancelled" ) when the user cancels or the
          expeditor times out, carrying the notification status
        - ValueError when the factory cannot build the matched command
    """
    from cosa.agents.runtime_argument_expeditor.agent_registry import JOB_ARG_CONTRACTS
    from cosa.agents.runtime_argument_expeditor.expeditor import RuntimeArgumentExpeditor, ExpediteContext
    from cosa.rest.agentic_job_factory import create_agentic_job
    from cosa.config.configuration_manager import ConfigurationManager

    voice_command   = args.voice_command
    matched_command = match_voice_command( voice_command, JOB_ARG_CONTRACTS )
    if not matched_command:
        available = [ c for c in JOB_ARG_CONTRACTS.keys() if c != MOCK_COMMAND ]
        raise ValueError( f"Could not match voice command to any agentic agent. Available: {available}" )

    session_id = f"expeditor-test-{user_id[ :8 ]}" if user_id else "expeditor-test"
    expeditor  = RuntimeArgumentExpeditor(
        config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" ),
        debug      = debug,
        verbose    = False
    )
    expeditor_job_id = f"exp-{uuid.uuid4().hex[ :8 ]}"   # notifications route to a dedicated card
    context          = ExpediteContext()

    resolved = expeditor.expedite(
        command           = matched_command,
        raw_args          = "",
        user_email        = user_email or "test@test.com",
        session_id        = session_id,
        user_id           = user_id or "test-user",
        original_question = voice_command,
        job_id            = expeditor_job_id,
        bearer_token      = bearer_token,
        context           = context
    )
    if resolved is None:
        raise SubmitRefused(
            route_reason = "expeditor_cancelled",
            message      = "Expeditor test: user cancelled or timed out",
            details      = { "config": {
                "command"             : matched_command,
                "voice_command"       : voice_command,
                "result"              : "cancelled_or_timeout",
                "args_found"          : None,
                "notification_status" : context.notification_status,
            } },
        )

    resolved[ "dry_run" ] = True
    if args.force_failure_mode is not None:
        resolved[ "force_failure_mode" ] = args.force_failure_mode
    job = create_agentic_job(
        command    = matched_command,
        args_dict  = resolved,
        user_id    = user_id or "test-user",
        user_email = user_email or "test@test.com",
        session_id = session_id,
        debug      = debug
    )
    if job is None:
        raise ValueError( f"Expeditor test: the factory could not build {matched_command}" )

    mode = f", force_failure_mode={args.force_failure_mode}" if args.force_failure_mode else ""
    job.submit_details = { "config": {
        "command"            : matched_command,
        "voice_command"      : voice_command,
        "args_resolved"      : { k: str( v ) for k, v in resolved.items()
                                 if k not in ( "user_email", "session_id", "user_id", "no_confirm" ) },
        "dry_run"            : True,
        "force_failure_mode" : args.force_failure_mode,
    }, "message": f"Expeditor test: {matched_command} (dry_run=True{mode})" }
    return job
