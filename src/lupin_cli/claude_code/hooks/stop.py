#!/usr/bin/env python3
"""
Stop hook: voice-driven blocking + stop observability.

When the voice buffer has content, blocks the stop and injects the voice
content as the reason — Claude processes the user's voice input instead
of stopping. When the buffer is empty, allows the stop.

Safety valve: MAX_STOP_BLOCKS consecutive blocks before force-allowing stop.
Loop prevention: if stop_hook_active is True, the hook is being re-invoked
after a block — don't block again.

Install in ~/.claude/settings.json:
    "hooks": {
        "Stop": [{
            "type": "command",
            "command": "python3 \"$LUPIN_ROOT/src/lupin_cli/claude_code/hooks/stop.py\""
        }]
    }
"""
import os
import sys

# Bootstrap: ensure src/ is on PYTHONPATH for lupin_cli imports
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:   # pragma: no cover - bootstrap import-guard; src is always on sys.path under pytest
    sys.path.insert( 0, _src_path )

from lupin_cli.claude_code.hooks.lib.hook_common import (
    read_hook_input, log_payload, log_to_stream, emit_json, send_tts,
    drain_and_acknowledge, format_voice_context, build_stop_block,
    inject_qualifier_via_tmux,
    enrich_voice_context, get_stop_block_count, increment_stop_block_count,
    reset_stop_block_count, get_turn_elapsed_seconds, MAX_STOP_BLOCKS
)
from lupin_cli.claude_code.hooks.lib.session_bridge import (
    get_claude_session_id, build_sender_id_for_cc, resolve_stable_session_id,
    get_speakerphone, get_session_metadata, get_voice_persona,
    get_idle_detection, set_idle_detection_field, kill_idle_waiter,
    get_last_autonarrated_turn_id, set_last_autonarrated_turn_id,
)
from lupin_cli.notifications.notify_user_sync import notify_user_sync
from lupin_cli.notifications.notify_user_async import notify_user_async
from lupin_cli.notifications.notification_models import (
    NotificationRequest, ResponseType, NotificationPriority, AsyncNotificationRequest
)
from cosa.utils.notification_utils import extract_qualifier_comment
from lupin_cli.claude_code.hooks.lib.idle_settings import load_idle_settings
from cosa.config.configuration_manager import ConfigurationManager
from lupin_cli.claude_code.hooks.lib.anything_else_ask import (
    fire_anything_else_ask, summarize_task as _shared_summarize_task,
)
# ── Heartbeat Hook (Branch-C self-poke) — additive, gated, downstream of the
#    stop_hook_active loop guard; voice always wins. Leaf modules are pure +
#    100%-covered; this file holds only the thin adapter. See:
#    src/rnd/v0.1.8/2026.06.04-heartbeat-hook/02-stop-py-seam-factoring-proposal.md
from lupin_cli.claude_code.hooks.lib.heartbeat_hold import read_hold
from lupin_cli.claude_code.hooks.lib.heartbeat_poke_cap import (
    get_poke_count, increment_poke_count,
)
from lupin_cli.claude_code.hooks.lib.heartbeat_decision import (
    decide_heartbeat, OUTCOME_POKE, OUTCOME_NOT_OWED, OUTCOME_HONORED, OUTCOME_CAP_REACHED,
)
from lupin_cli.claude_code.hooks.lib.heartbeat_settings import load_heartbeat_settings
from lupin_cli.claude_code.hooks.lib import heartbeat_events
# v2 Track-A — live work-owed oracle (Task* replay from the session transcript).
from lupin_cli.claude_code.hooks.lib.heartbeat_work_owed import evaluate_work_owed
from lupin_cli.claude_code.hooks.lib.heartbeat_task_state import (
    replay_task_state, owed_items_from_state, is_empty_state,
)


def _summarize_task( last_assistant_message ):
    """
    Summarize the last assistant message using Gister (default mode).

    Requires:
        - last_assistant_message is a string or None

    Ensures:
        - Returns a concise gist string on success
        - Returns None on any failure or empty input
    """
    if not last_assistant_message or not last_assistant_message.strip():
        return None

    try:
        from cosa.memory.gister import Gister
        gister = Gister( debug=False, verbose=False )
        gist   = gister.get_gist( last_assistant_message, prompt_key="prompt template for stop hook gist" )
        return gist if gist else None
    except Exception:
        return None


# NOTE: classify_qualifier() is commented out because its synchronous LLM
# call to phi4 exceeds Claude Code's stop hook subprocess timeout (~5-10s).
# Preserved for future use in non-time-critical contexts.
#
# def classify_qualifier( qualifier ):
#     """
#     Classify a user qualifier as 'question' or 'instruction' via phi4 LLM.
#
#     Follows the established agent pattern:
#         1. Load prompt template path from config
#         2. Process template via PromptTemplateProcessor (injects XML example)
#         3. Format with utterance
#         4. Call LLM via LlmClientFactory
#         5. Parse response via QualifierClassification.from_xml()
#
#     Requires:
#         - qualifier is a non-empty string
#
#     Ensures:
#         - Returns QualifierClassification instance on success
#         - Returns None on any failure (LLM unreachable, parse error, etc.)
#     """
#     try:
#         import cosa.utils.util as du
#         from cosa.config.configuration_manager import ConfigurationManager
#         from cosa.agents.llm_client_factory import LlmClientFactory
#         from cosa.agents.io_models.xml_models import QualifierClassification
#         from cosa.agents.io_models.utils.util_xml_pydantic import XMLParsingError
#         from cosa.agents.io_models.utils.prompt_template_processor import PromptTemplateProcessor
#
#         config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
#
#         # Load and process prompt template
#         prompt_template_path = config_mgr.get( "prompt template for qualifier classification" )
#         prompt_template      = du.get_file_as_string( du.get_project_root() + prompt_template_path )
#
#         processor       = PromptTemplateProcessor()
#         prompt_template = processor.process_template( prompt_template, "qualifier classification" )
#         prompt          = prompt_template.format( utterance=qualifier )
#
#         # Call LLM
#         llm_spec_key = config_mgr.get( "llm spec key for qualifier classification" )
#         llm_client   = LlmClientFactory().get_client( llm_spec_key )
#         raw_response = llm_client.run( prompt )
#
#         # Parse structured XML response
#         return QualifierClassification.from_xml( raw_response )
#
#     except ( XMLParsingError, Exception ):
#         return None


# Minimum turn duration (seconds) to consider work "substantive"
MIN_TURN_DURATION_SECONDS = 10


def _should_ask_anything_else( last_assistant_message, session_id ):
    """
    Determine whether the stop hook should prompt "Anything else?"

    Two-signal gate:
        1. Empty last_assistant_message → no work done → skip
        2. Turn duration < threshold → trivial turn → skip

    Requires:
        - last_assistant_message is a string or None
        - session_id is a string

    Ensures:
        - Returns False if no substantive work was done
        - Returns True if both signals indicate real work
    """
    # Signal 1: No assistant output at all
    if not last_assistant_message or not last_assistant_message.strip():
        log_to_stream( "stop", {}, extra={
            "phase"  : "gate_skip",
            "reason" : "empty last_assistant_message"
        } )
        return False

    # Signal 2: Turn was too short
    elapsed = get_turn_elapsed_seconds( session_id )
    if elapsed is not None and elapsed < MIN_TURN_DURATION_SECONDS:
        log_to_stream( "stop", {}, extra={
            "phase"   : "gate_skip",
            "reason"  : "turn_too_short",
            "elapsed" : round( elapsed, 1 )
        } )
        return False

    return True


def _get_session_context( cwd ):
    """
    Read session topic from bridge file + git branch name.

    Requires:
        - cwd is a string path or None

    Ensures:
        - Returns (topic, branch) tuple
        - topic is a string or None (from bridge file's session_topic)
        - branch is a string or None (from git rev-parse)
        - Never raises exceptions
    """
    topic  = None
    branch = None

    # Session topic from bridge file
    try:
        from lupin_cli.claude_code.hooks.lib.session_bridge import get_session_metadata
        meta  = get_session_metadata()
        topic = meta.get( "session_topic" )
    except Exception:
        pass

    # Git branch
    if cwd:
        try:
            import subprocess
            branch = subprocess.check_output(
                [ "git", "rev-parse", "--abbrev-ref", "HEAD" ],
                cwd=cwd, text=True, timeout=5
            ).strip()
        except Exception:
            pass

    return topic, branch


DEFAULT_IDLE_BEHAVIOR = "idle_announce"
_VALID_IDLE_BEHAVIORS = ( "none", "ask", "idle_announce" )


def _stop_hook_idle_behavior() -> str:
    """
    Thread A 3-way toggle: what does the Stop hook do on a no-poke (idle) Stop?

    Returns one of:
        - "none"          → take no action, just allow the stop (silent).
        - "ask"           → the legacy idle-waiter / "Anything else?" path
                            (load_idle_settings → _arm_idle_waiter or
                            _ask_anything_else).
        - "idle_announce" → (DEFAULT) fire ONE low-priority idle status notify
                            (the persona "speaks" its idle state), then allow
                            the stop. v2.1 direct-state visibility owns fleet
                            liveness; this is just a lightweight courtesy ping.

    Read from `lupin-app.ini [Lupin: Baseline] stop hook idle behavior` via the
    ConfigurationManager (project mandate: config lives in lupin-app.ini with a
    matching splainer entry). The Stop hook fires per-TURN (not per-tool), so the
    parse cost is acceptable; the read is wrapped in redirect_stdout because the
    ConfigurationManager banners would otherwise corrupt the hook's stdout JSON
    protocol channel.

    Ensures:
        - returns one of _VALID_IDLE_BEHAVIORS
        - fail-safe to DEFAULT_IDLE_BEHAVIOR ("idle_announce") on any error, a
          missing key, or an unrecognized value
        - never raises; never writes to stdout
    """
    import contextlib
    import io
    try:
        with contextlib.redirect_stdout( io.StringIO() ):
            mgr   = ConfigurationManager(
                env_var_name = "LUPIN_CONFIG_MGR_CLI_ARGS",
                silent       = True,
                mute_splainer = True,
            )
            value = mgr.get( "stop hook idle behavior", default=DEFAULT_IDLE_BEHAVIOR, silent=True )
        value = str( value or DEFAULT_IDLE_BEHAVIOR ).strip().lower()
        return value if value in _VALID_IDLE_BEHAVIORS else DEFAULT_IDLE_BEHAVIOR
    except Exception:
        return DEFAULT_IDLE_BEHAVIOR


def _idle_sentence( persona_name ) -> str:
    """
    The first-person idle status sentence for the `idle_announce` behavior
    (seeded from the dropped poke-scaffold's NOT_OWED case). Pure.

    Ensures:
        - returns "I'm <persona>. Idle — nothing owed." ("a worker" when the
          persona name is missing)
    """
    return f"I'm {persona_name or 'a worker'}. Idle — nothing owed."


def _announce_idle( session_id, persona_name ):
    """
    Fire ONE low-priority, non-blocking idle status notify for the
    `idle_announce` behavior. The persona "speaks" its own idle state.

    A SINGLE low-pri fire-and-forget notify (NOT the dropped per-outcome
    poke-report spam): the per-Stop /api/notify push is cheap now that the
    prediction hot path is offloaded via asyncio.to_thread (f3cfabf), but it
    stays low-priority + failsafe so it never dings and never blocks the Stop.

    Ensures:
        - posts a low-priority AsyncNotificationRequest carrying _idle_sentence,
          stamped with this session's CC sender_id so it renders AS the persona
        - NEVER raises / never blocks the Stop (try/except; mirrors the
          emit-outcome invariant)
    """
    try:
        request = AsyncNotificationRequest(
            message   = _idle_sentence( persona_name ),
            priority  = NotificationPriority.LOW,
            sender_id = build_sender_id_for_cc( session_id ),
            abstract  = "Heartbeat: idle — nothing owed.",
        )
        notify_user_async( request )
    except Exception as e:
        log_to_stream( "stop", {}, extra={
            "phase"      : "idle_announce_error",
            "session_id" : session_id,
            "error"      : str( e ),
        } )


def _arm_idle_waiter( session_id, last_assistant_message, cwd ):
    """
    Spawn a deferred-ask waiter instead of firing "Anything else?" immediately.

    The waiter sleeps for `backoff_minutes[backoff_index]` minutes (from
    settings.idle_detection), then re-checks the bridge for reset signals.
    If still idle, it fires the same "Anything else?" prompt the legacy
    immediate-ask path would have fired.

    Pre-computes the Gister gist NOW (Stop hook context) and stores it on
    the bridge so the waiter doesn't need to call Gister at wake time.

    Reads `backoff_index` from the bridge — preserves backoff progression
    across multiple Stop fires when the user never came back to interact.
    UserPromptSubmit hook resets it to 0 on user activity.

    See: src/rnd/v0.1.7/2026.04.29-idle-aware-stop-hook/01-design.md

    Requires:
        - session_id is a non-empty string
        - last_assistant_message is a string or None (for gist computation)
        - cwd is a string path or None

    Ensures:
        - Kills any prior waiter for this session (idempotent)
        - Bumps last_interaction_at, stores gist + waiter spawn metadata in bridge
        - Spawns detached idle_waiter.py subprocess
        - Returns the spawned waiter PID, or None on spawn failure
        - Never raises — spawn failure logs and returns None

    Args:
        session_id            : CC session ID
        last_assistant_message: Claude's last response text (for gist)
        cwd                   : Working dir for git-branch resolution

    Returns:
        int or None: Spawned waiter PID, or None on failure
    """
    import datetime
    import subprocess
    from pathlib import Path

    # Pre-compute gist while we have last_assistant_message (waiter doesn't)
    gist = _shared_summarize_task( last_assistant_message )

    # Read current backoff_index — preserved across Stop fires until UserPromptSubmit
    # resets it to 0. UserPromptSubmit fires only on user activity; consecutive
    # Stops without user activity should resume the backoff schedule, not restart it.
    state         = get_idle_detection( session_id ) or { }
    current_index = state.get( "backoff_index", 0 ) or 0

    # Resolve CC PID from bridge (set by SessionStart). Fallback to hook's
    # grandparent walk if bridge doesn't have it.
    meta   = get_session_metadata()
    cc_pid = meta.get( "cc_pid" ) or os.getppid()

    # Kill any stale waiter so we don't end up with parallel asks
    kill_idle_waiter( session_id )

    # Bump last_interaction_at + store gist + carry cwd for the waiter's
    # session-context resolution at wake-time
    set_idle_detection_field(
        session_id,
        last_interaction_at = datetime.datetime.now().astimezone().isoformat( timespec="seconds" ),
        last_task_gist      = gist,
        last_task_cwd       = cwd,
    )

    # Spawn the waiter — mirrors register_session.py:_spawn_listener pattern
    short    = session_id[ :8 ] if session_id else "unknown"
    log_path = Path( os.path.expanduser( f"~/.claude/sessions/cc-idle-waiter-{short}.log" ) )

    cmd = [
        sys.executable, "-m", "lupin_cli.claude_code.hooks.lib.idle_waiter",
        "--session-id"   , session_id,
        "--cc-pid"       , str( cc_pid ),
        "--backoff-index", str( current_index ),
    ]
    # Test-mode hook: if env tells us to use a short sleep, propagate it
    test_sleep = os.environ.get( "LUPIN_IDLE_WAITER_TEST_SLEEP_SECS" )
    if test_sleep:
        cmd.extend( [ "--sleep-secs", test_sleep ] )

    env = os.environ.copy()
    env[ "PYTHONUNBUFFERED" ] = "1"
    if _src_path and _src_path not in env.get( "PYTHONPATH", "" ):
        env[ "PYTHONPATH" ] = _src_path + ":" + env.get( "PYTHONPATH", "" )
    if cwd:
        env[ "CC_HOOK_CWD" ] = cwd

    try:
        log_file = open( log_path, "a" )
    except OSError:
        log_file = subprocess.DEVNULL

    try:
        proc = subprocess.Popen(
            cmd,
            stdout            = log_file if log_file is not subprocess.DEVNULL else subprocess.DEVNULL,
            stderr            = log_file if log_file is not subprocess.DEVNULL else subprocess.DEVNULL,
            env               = env,
            start_new_session = True,
        )
        log_to_stream( "stop", {}, extra={
            "phase"         : "idle_waiter_armed",
            "waiter_pid"    : proc.pid,
            "backoff_index" : current_index,
            "cc_pid"        : cc_pid,
        } )
        return proc.pid
    except Exception as e:
        log_to_stream( "stop", {}, extra={
            "phase" : "idle_waiter_spawn_failed",
            "error" : str( e ),
        } )
        return None


def _ask_anything_else( session_id, last_assistant_message=None, cwd=None ):
    """
    Ask the user "Anything else?" via notify_user_sync with a 5-minute timeout.

    Returns the stop hook JSON to emit: block dict if user wants to continue,
    empty dict if user says no / timeout / error.

    Requires:
        - session_id is a string for sender_id resolution
        - last_assistant_message is a string or None
        - cwd is a string path or None (for session context resolution)

    Ensures:
        - Returns dict suitable for emit_json()
        - Notification message includes Gister summary when available
        - Qualifier is classified as question or instruction via LLM
        - "yes" blocks stop (with or without qualifier)
        - "no + qualifier" blocks stop and passes the qualifier as new work
        - Plain "no", timeout, error → allows stop ({})
        - On any exception, returns {} (allow stop gracefully)
    """
    try:
        sender_id = build_sender_id_for_cc( session_id )

        gist = _summarize_task( last_assistant_message )
        if gist:
            message = f'I\'m finished *"...{gist}"*. Is there anything else you want me to do?'
        else:
            message = "I've finished the current task. Is there anything else you'd like me to do?"

        # Build abstract with session-level context
        topic, branch = _get_session_context( cwd )
        parts = []
        if topic:
            parts.append( f"**Session**: {topic}" )
        if branch:
            parts.append( f"**Branch**: `{branch}`" )
        abstract = "  \n".join( parts ) if parts else None

        request = NotificationRequest(
            message                  = message,
            response_type            = ResponseType.YES_NO,
            priority                 = NotificationPriority.MEDIUM,
            timeout_seconds          = 60,
            response_default         = "no",
            title                    = "Stop hook: Anything else?",
            sender_id                = sender_id,
            abstract                 = abstract,
            display_qualifier_widget = True
        )

        response = notify_user_sync( request )

        answer, qualifier = extract_qualifier_comment( response.response_value )

        print( f"[STOP] response: exit_code={response.exit_code}, value='{response.response_value}'", file=sys.stderr )
        print( f"[STOP] parsed: answer='{answer}', qualifier='{qualifier}'", file=sys.stderr )

        log_to_stream( "stop", {}, extra={
            "phase"     : "ask_anything_else",
            "answer"    : answer,
            "qualifier" : qualifier,
            "raw_value" : response.response_value,
            "exit_code" : response.exit_code
        } )

        if answer == "yes":
            if qualifier:
                inject_qualifier_via_tmux( session_id, qualifier )
                log_to_stream( "stop", {}, extra={
                    "phase"  : "qualifier_tmux_inject",
                    "answer" : answer,
                    "text"   : qualifier
                } )
                return build_stop_block( f"User wants to continue. Qualifier injected via tmux: {qualifier}" )
            else:
                reason = "The user wants to continue working. Ask them what they'd like done next."
                log_to_stream( "stop", {}, extra={
                    "phase"  : "qualifier_block",
                    "answer" : answer,
                    "reason" : reason[ :120 ]
                } )
                return build_stop_block( reason )

        if answer == "no" and qualifier:
            inject_qualifier_via_tmux( session_id, qualifier )
            log_to_stream( "stop", {}, extra={
                "phase"  : "qualifier_tmux_inject",
                "answer" : answer,
                "text"   : qualifier
            } )
            return build_stop_block( f"User said no but attached work. Qualifier injected via tmux: {qualifier}" )

        # Plain "no", timeout, error → allow stop
        return {}

    except Exception as e:
        # Server down, network error, import error → allow stop gracefully
        send_tts( f"Stop — notify error: {e}" )
        return {}


# ── Phase 4 — Layer 3 Stop-hook auto-narrate ──────────────────────────────────
#
# Per src/rnd/v0.1.7/2026.04.30-conv-mode-three-layer-enforcement/01-design.md
# Phase 4: when conv mode is active and Claude's last assistant turn ended
# WITHOUT a notify() call, synthesize one so the user (listening at distance)
# hears the response. Safety net for the case where Claude's cached belief
# about conv mode drifts and it writes console-only.

import json as _json   # local alias to avoid shadowing


def _read_last_assistant_message( transcript_path ):
    """
    Read transcript JSONL, return the last assistant-role message dict.

    Claude Code transcripts are line-delimited JSON; each message has
    `type` ("user" or "assistant") and `message.content` (a list of
    content blocks). Iterate all lines, remember the most recent
    assistant message.

    Requires:
        - transcript_path is a non-empty string path

    Ensures:
        - Returns the last assistant message dict or None
        - Returns None on missing file, parse error, or no assistant
        - Never raises

    Args:
        transcript_path: Path to JSONL transcript file

    Returns:
        dict or None: Last assistant message
    """
    if not transcript_path or not os.path.isfile( transcript_path ):
        return None
    last_assistant = None
    try:
        with open( transcript_path ) as f:
            for line in f:
                line = line.strip()
                if not line: continue
                try:
                    msg = _json.loads( line )
                except _json.JSONDecodeError:
                    continue
                if msg.get( "type" ) == "assistant":
                    last_assistant = msg
    except OSError:
        return None
    return last_assistant


def _turn_has_notify_call( assistant_msg ):
    """
    Check if the assistant message contains a mcp__cosa-voice__notify
    ToolUseBlock. If yes, Claude self-narrated and auto-narrate should
    pass through.

    Requires:
        - assistant_msg is a dict from _read_last_assistant_message

    Ensures:
        - Returns True if any content block has type="tool_use" and
          name=="mcp__cosa-voice__notify"
        - Returns False otherwise (incl. on shape mismatch / missing fields)
        - Never raises

    Args:
        assistant_msg: Assistant message dict

    Returns:
        bool: Whether Claude self-narrated
    """
    try:
        content = assistant_msg.get( "message", { } ).get( "content", [ ] )
        for block in content:
            if isinstance( block, dict ):
                if block.get( "type" ) == "tool_use" and block.get( "name" ) == "mcp__cosa-voice__notify":
                    return True
    except Exception:
        pass
    return False


def _extract_narratable_text( assistant_msg ):
    """
    Extract speakable text from an assistant message: concatenate text
    blocks, strip fenced code blocks, trim whitespace.

    Requires:
        - assistant_msg is a dict from _read_last_assistant_message

    Ensures:
        - Returns concatenated text from all "text" content blocks
        - Fenced code blocks stripped via strip_fenced_code_blocks
          (imported from lupin_mcp.cosa_voice_mcp — same impl Phase 3 uses)
        - Returns empty string if no text content or on shape mismatch

    Args:
        assistant_msg: Assistant message dict

    Returns:
        str: Narratable text (may be empty)
    """
    try:
        content = assistant_msg.get( "message", { } ).get( "content", [ ] )
        parts   = [ ]
        for block in content:
            if isinstance( block, dict ) and block.get( "type" ) == "text":
                text = block.get( "text", "" )
                if text:
                    parts.append( text )
        joined = "\n\n".join( parts ).strip()
        if not joined:
            return ""
        try:
            from lupin_mcp.cosa_voice_mcp import strip_fenced_code_blocks
            joined = strip_fenced_code_blocks( joined )
        except Exception:
            pass  # Stripping is best-effort
        return joined.strip()
    except Exception:
        return ""


def _try_auto_narrate( session_id, payload ):
    """
    Phase 4 Layer 3 safety net: if Claude's last assistant turn in conv
    mode ended without a notify() call, synthesize one via send_tts.

    See: src/rnd/v0.1.7/2026.04.30-conv-mode-three-layer-enforcement/01-design.md

    Requires:
        - session_id is a non-empty string
        - payload is a dict (Stop-hook payload)
        - conv mode is already verified active by the caller

    Ensures:
        - Reads transcript_path from payload (or bridge metadata fallback)
        - If last assistant turn already contains notify() ToolUseBlock,
          pass through (Claude self-narrated)
        - If last_autonarrated_turn_id matches current turn id, pass through
          (already narrated this turn — re-fire dedup)
        - Otherwise: extract narratable text, strip code, call send_tts
          with priority='high' + suppress_ding=True (conv-mode params),
          stamp the turn id in the bridge for future dedup
        - Never raises (failures are logged via log_to_stream)
    """
    transcript_path = payload.get( "transcript_path" ) or ""
    if not transcript_path:
        try:
            meta            = get_session_metadata()
            transcript_path = meta.get( "transcript_path" ) or ""
        except Exception:
            transcript_path = ""
    if not transcript_path:
        log_to_stream( "stop", { }, extra={
            "phase"      : "auto_narrate_skip",
            "reason"     : "no transcript_path",
            "session_id" : session_id,
        } )
        return

    last_msg = _read_last_assistant_message( transcript_path )
    if not last_msg:
        log_to_stream( "stop", { }, extra={
            "phase"      : "auto_narrate_skip",
            "reason"     : "no assistant message in transcript",
            "session_id" : session_id,
        } )
        return

    if _turn_has_notify_call( last_msg ):
        log_to_stream( "stop", { }, extra={
            "phase"      : "auto_narrate_skip",
            "reason"     : "claude self-narrated",
            "session_id" : session_id,
        } )
        return

    turn_id = last_msg.get( "uuid" ) or last_msg.get( "id" ) or ""
    if turn_id and get_last_autonarrated_turn_id( session_id ) == str( turn_id ):
        log_to_stream( "stop", { }, extra={
            "phase"      : "auto_narrate_skip",
            "reason"     : "already auto-narrated this turn",
            "session_id" : session_id,
            "turn_id"    : turn_id,
        } )
        return

    narration = _extract_narratable_text( last_msg )
    if not narration:
        log_to_stream( "stop", { }, extra={
            "phase"      : "auto_narrate_skip",
            "reason"     : "no narratable text",
            "session_id" : session_id,
        } )
        return

    # Synthesize narration with conv-mode params
    try:
        send_tts(
            narration,
            priority      = "high",
            suppress_ding = True
        )
        if turn_id:
            set_last_autonarrated_turn_id( session_id, turn_id )
        log_to_stream( "stop", { }, extra={
            "phase"      : "auto_narrate_fired",
            "session_id" : session_id,
            "turn_id"    : turn_id,
            "char_count" : len( narration ),
        } )
    except Exception as e:
        log_to_stream( "stop", { }, extra={
            "phase"      : "auto_narrate_error",
            "session_id" : session_id,
            "error"      : str( e ),
        } )


def _notify_cap_reached( session_id ):
    """
    Observability FYI when the heartbeat poke-cap is reached (§0 #6).

    v1 = log-only. The richer USER-FACING async notify ("max auto-nudges
    reached, awaiting user" — the §0 #6 intent that the user eventually learns
    nudging stopped) is deferred to v1.1: the only sync hook primitive,
    notify_user_sync, is SSE-BLOCKING (response-required) and would HANG the
    Stop hook — wrong for a fire-and-forget FYI. log_to_stream is non-blocking,
    zero-server-dependency, and greppable in io/claude_code_hooks/ captures.

    Requires:
        - session_id is a string

    Ensures:
        - Emits a "heartbeat_cap_reached" log record carrying session_id +
          poke_count (greppable); never raises, never blocks the stop
    """
    log_to_stream( "stop", {}, extra={
        "phase"      : "heartbeat_cap_reached",
        "session_id" : session_id,
        "poke_count" : get_poke_count( session_id ),
        # v1.1: also fire a user-facing async notify here (§0 #6) — deferred;
        # notify_user_sync is SSE-blocking and cannot be used in a Stop hook.
    } )


def _emit_genuine_idle( session_id, persona_name, cap ):
    """
    Genuine-idle DECLARATION beacon (Rick §6.2 = Option B), edge-triggered.

    Called only when this Stop is genuinely idle (not_owed AND an empty Task*
    set). De-dup is delegated to heartbeat_events.is_idle_transition (a tested
    pure helper, Tiffany's lane): emit the beacon ONLY on the TRANSITION into
    idle — sticky-until-superseded, so a quiet streak writes ONE beacon, not one
    per Stop. Fire-and-forget: wrapped so a write/read failure NEVER breaks the
    poke path (mirrors the poke-outcome emit invariant, §0 #2).

    Requires:
        - session_id is a string
        - persona_name is a string or None
        - cap is the per-session poke-cap int

    Ensures:
        - Appends one outcome="idle" event iff this is the transition into idle
        - work_owed=False (genuinely idle); no reason
        - Never raises, never blocks the stop
    """
    try:
        if heartbeat_events.is_idle_transition( session_id ):
            heartbeat_events.emit_outcome(
                session_id,
                persona_name,
                heartbeat_events.EVENT_IDLE,
                get_poke_count( session_id ),
                cap,
                work_owed = False,
                awaiting  = None,
            )
    except Exception as e:
        log_to_stream( "stop", {}, extra={
            "phase"      : "heartbeat_idle_emit_error",
            "session_id" : session_id,
            "error"      : str( e ),
        } )


def _run_heartbeat( session_id, transcript_path ):
    """
    Branch-C heartbeat self-poke adapter (thin; composes the pure leaf modules).

    The §0 5-step decision logic lives entirely in the pure, 100%-covered leaf
    modules (heartbeat_hold / heartbeat_work_owed / heartbeat_poke_cap /
    heartbeat_decision). This adapter is ONLY the side-effecting shell: read the
    hold + poke count + live work-owed verdict, call decide_heartbeat, apply the
    increment / cap-FYI / emit side effects it signals, and return the block
    dict to emit when (and only when) the heartbeat owns this stop.

    **v2 scope (Task* live oracle — §0.3, corrected TodoWrite→Task*):** the
    work-owed verdict comes from the session's OWN Task* state, replayed from
    its transcript (`transcript_path`). So v2 ALSO catches the FM-19
    undeclared-lazy-stop case: a session with NO hold that stops with owed Task*
    work (in_progress / pending) is poked. v1 behavior is preserved — a fresh
    reasoned hold is still honored; the hold's self-declared work_owed still
    wins over the oracle (decide_heartbeat order). `owned_by_me` is TRUE by
    construction (the Task* calls live in THIS session's transcript). The
    transcript read is `:7999`-free and never a dependency of the poke (the
    reader never raises; a missing/empty transcript ⇒ no owed work ⇒
    conservative).

    Gated by ~/.claude/settings.json ["heartbeat"]["enabled"] (DEFAULT False).
    A malformed config (ValueError from the loader) fails SAFE → disabled.

    Requires:
        - session_id is a string
        - transcript_path is the Stop-hook payload's transcript_path (str/None)
        - called ONLY from Branch C (no voice_ctx), DOWNSTREAM of the
          stop_hook_active loop guard — voice always wins; never poke on a
          re-fire

    Ensures:
        - Returns {"decision":"block","reason": …} ONLY when the heartbeat
          pokes (OUTCOME_POKE) — the caller emits it and skips the idle path
        - Returns None on disabled / malformed config / honored hold / nothing
          owed / cap reached — the caller falls through to the existing
          idle-waiter / "Anything else?" path UNCHANGED
        - Applies the counter increment (on poke) + cap FYI (at cap) +
          fire-and-forget event emission side effects
    """
    try:
        settings = load_heartbeat_settings()
    except ValueError as e:
        # Malformed heartbeat config — fail SAFE (never poke on bad config).
        log_to_stream( "stop", {}, extra={
            "phase"      : "heartbeat_settings_invalid",
            "session_id" : session_id,
            "error"      : str( e ),
        } )
        return None

    if not settings[ "enabled" ]:
        return None

    hold       = read_hold( session_id )
    poke_count = get_poke_count( session_id )
    # v2: REAL work-owed verdict from the session's own Task* state, replayed
    # from its transcript (§0.3). owned_by_me TRUE by construction; :7999-free;
    # the reader never raises (missing/empty transcript ⇒ no owed work).
    # v2.1 perf: replay the transcript ONCE and derive BOTH the owed-items and
    # the genuine-idle empty-set signal from the single state (the Stop hook
    # fires every turn — halves the per-Stop transcript reads).
    task_state = replay_task_state( transcript_path )
    owed_items = owed_items_from_state( task_state )
    verdict    = evaluate_work_owed( todo_items=owed_items )
    result     = decide_heartbeat( hold, verdict, poke_count, settings[ "poke_cap" ] )

    if result[ "should_increment" ]:
        increment_poke_count( session_id )
    if result[ "should_notify_cap" ]:
        _notify_cap_reached( session_id )

    # ── EMIT NOW, CONSUME LATER (María §0 #2) ──────────────────────────────────
    # Fire-and-forget poke-OUTCOME record so the v2 agentic Poker lands later as
    # a PURE CONSUMER (zero Hook retrofit). emit_outcome SELF-FILTERS (writes
    # only for {poke, honored, cap_reached}; no-op on not_owed/unknown) — called
    # unconditionally, no branching. Writes to the FLEET dir
    # ~/.claude/heartbeat-events/ (outside the repo); :7999-free. The try/except
    # makes emission NEVER a dependency of the poke: if it fails the poke still
    # proceeds (the §0 #2 invariant) — belt to emit_outcome's never-raises belt.
    persona      = get_voice_persona( session_id )
    persona_name = persona.get( "name" ) if persona else None

    # ── Live oracle log line (2026-06-05, Rick) — "signs of life" every Stop ──
    # Greppable in the stop log stream (`docker logs … | grep heartbeat_oracle`):
    # the work-owed verdict + decision outcome + poke count, so you can watch the
    # Oracle's state update in real time and confirm it's accurate + current.
    log_to_stream( "stop", {}, extra={
        "phase"      : "heartbeat_oracle",
        "session_id" : session_id,
        "persona"    : persona_name,
        "outcome"    : result[ "outcome" ],
        "work_owed"  : verdict[ "work_owed" ],
        "owed_items" : len( owed_items ),
        "poke_count" : get_poke_count( session_id ),
        "cap"        : settings[ "poke_cap" ],
        "awaiting"   : ( hold.get( "awaiting" ) if hold else None ),
    } )

    try:
        heartbeat_events.emit_outcome(
            session_id,
            persona_name,
            result[ "outcome" ],
            get_poke_count( session_id ),                       # POST-increment
            settings[ "poke_cap" ],
            work_owed = verdict[ "work_owed" ],                 # v2: REAL bool (was null in v1)
            awaiting  = ( hold.get( "awaiting" ) if hold else None ),
            reason    = result[ "hook_output" ].get( "reason" ),  # poke text, else None
        )
    except Exception as e:
        log_to_stream( "stop", {}, extra={
            "phase"      : "heartbeat_emit_error",
            "session_id" : session_id,
            "error"      : str( e ),
        } )
    # ── end emit ──
    #
    # NOTE (Thread A, 2026-06-06): the 2026-06-05 on-behalf "poke-report" scaffold
    # (_heartbeat_state_sentence + _send_poke_report, a per-Stop /api/notify PUSH)
    # was DROPPED here — superseded by v2.1 direct-state visibility, which makes
    # liveness a cheap centrally-PULLED bridge-mtime age instead of an expensive
    # per-Stop push (the push was the FM-7 load multiplier). The poke, oracle log,
    # and genuine-idle beacon below all remain live. See
    # src/rnd/v0.1.8/2026.06.06-heartbeat-poke-scaffold-vs-v2.1-supersession.md.

    # ── 2b: genuine-idle DECLARATION beacon (Rick §6.2 = Option B) ─────────────
    # Edge-triggered: declare idle ONLY on the TRANSITION into genuine-idle
    # (not_owed AND an empty Task* set), de-duped against the last emitted event
    # so a quiet streak emits ONE beacon, not one per Stop. Fire-and-forget.
    if result[ "outcome" ] == OUTCOME_NOT_OWED and is_empty_state( task_state ):
        _emit_genuine_idle( session_id, persona_name, settings[ "poke_cap" ] )

    if result[ "outcome" ] == OUTCOME_POKE:
        return result[ "hook_output" ]
    return None


def main():

    payload = read_hook_input()
    if not payload:
        emit_json( {} )
        sys.exit( 0 )

    # Extract stop_hook_active for loop prevention
    stop_hook_active = payload.get( "stop_hook_active", "NOT_PRESENT" )

    # Log full payload for empirical analysis
    log_payload( "stop", payload )

    # Resolve session_id: payload first, then session bridge fallback
    session_id = resolve_stable_session_id( payload.get( "session_id", "" ) ) or get_claude_session_id()

    # Conversation mode: skip the "Anything else?" prompt path (would
    # interrupt the user's voice dialogue), but FIRST run the Phase 4
    # auto-narrate safety net — synthesize a notify() if Claude's last
    # turn ended without one (silent-console-only failure mode). Per
    # src/rnd/v0.1.7/2026.04.30-conv-mode-three-layer-enforcement/01-design.md
    if get_speakerphone( session_id ):
        try:
            _try_auto_narrate( session_id, payload )
        except Exception as e:
            log_to_stream( "stop", { }, extra={
                "phase"      : "auto_narrate_error",
                "session_id" : session_id,
                "error"      : str( e ),
            } )
        # Silent idle-announce (Rick, 2026-06-08). Speakerphone sessions previously
        # exited here BEFORE the idle-behavior gate (~line 1063), so idle_announce
        # never fired for them — an order-of-operations bug (the early-exit was
        # written for the BLOCKING "Anything else?" ask path, never narrowed when the
        # non-blocking idle_announce became default). Fire it here instead, SILENTLY:
        # _announce_idle posts at LOW priority, which the client renders to the DOM
        # card WITHOUT TTS (notifications.js gates speech on high/urgent only) — a
        # subtle bubble, no chorus-TTS spam. Gated to idle_announce ONLY: `ask`/`none`
        # stay fully silent in speakerphone (the blocking ask is correctly skipped).
        # "Nothing owed" is a turn-boundary approximation — this runs upstream of the
        # work-owed oracle (accepted by Rick).
        if _stop_hook_idle_behavior() == "idle_announce":
            persona      = get_voice_persona( session_id )
            persona_name = persona.get( "name" ) if persona else None
            _announce_idle( session_id, persona_name )

        # Speakerphone/chorus sessions skip the "Anything else?" prompt + heartbeat
        # path entirely (it would interrupt the user's live voice dialogue); the
        # auto-narrate safety net above is preserved. Restored to clean
        # pre-experiment behavior (Thread A, 2026-06-06 — the 2026-06-05 comment-out
        # was incidental experiment debris).
        log_to_stream( "stop", {}, extra={
            "phase"      : "speakerphone_skip",
            "session_id" : session_id,
        } )
        emit_json( {} )
        sys.exit( 0 )

    # Loop prevention: if stop_hook_active is True, we already blocked once —
    # don't block again (would create infinite loop)
    if stop_hook_active is True:
        emit_json( {} )
        sys.exit( 0 )

    # Drain voice buffer and acknowledge buffered messages
    messages  = drain_and_acknowledge( session_id )
    voice_ctx = format_voice_context( messages )

    if voice_ctx:
        # Check block counter — safety valve
        count = get_stop_block_count( session_id )
        if count >= MAX_STOP_BLOCKS:
            reset_stop_block_count( session_id )
            send_tts( "Stop — max blocks reached, allowing stop" )
            emit_json( {} )
        else:
            increment_stop_block_count( session_id )
            send_tts( "Stop — blocking with voice input" )
            emit_json( build_stop_block( enrich_voice_context( voice_ctx ) ) )
    else:
        # No voice input → ask user "Anything else?" via notification.
        # Two paths gated by ~/.claude/settings.json idle_detection.enabled:
        #   - enabled=true (default, NEW): arm a deferred waiter and allow stop
        #     immediately. The waiter sleeps for backoff_minutes[index] minutes,
        #     then re-checks the bridge and fires the same prompt only if the
        #     session is still idle. See:
        #     src/rnd/v0.1.7/2026.04.29-idle-aware-stop-hook/01-design.md
        #   - enabled=false (LEGACY): fire the prompt immediately as before.
        reset_stop_block_count( session_id )

        # ── Heartbeat self-poke (additive; gated; voice already lost above) ──
        # Downstream of the stop_hook_active loop guard (never poke on a
        # re-fire) and only in Branch C (no voice_ctx → voice always wins).
        # Returns a block dict ONLY when the heartbeat pokes; otherwise None →
        # fall through to the existing idle-waiter / "Anything else?" path.
        # transcript_path (Stop payload) feeds the v2 Task*-replay work-owed oracle.
        heartbeat_output = _run_heartbeat( session_id, payload.get( "transcript_path" ) )
        if heartbeat_output is not None:
            emit_json( heartbeat_output )
            return
        # ── end heartbeat ──

        # ── Idle-Stop behavior (Thread A — 3-way enum) ────────────────────────
        # On a no-poke (idle) Stop, `lupin-app.ini [Lupin: Baseline] stop hook
        # idle behavior` selects the action. v2.1 direct-state visibility owns
        # fleet liveness now, so the legacy idle-waiter is no longer the default:
        #   - "idle_announce" (DEFAULT) → fire ONE low-pri idle status notify
        #     (the persona speaks its idle state), then allow the stop.
        #   - "ask"   → the legacy path verbatim: deferred idle-waiter
        #     (idle_detection enabled) or the immediate "Anything else?" prompt.
        #   - "none"  → take no action, just allow the stop (silent).
        idle_behavior = _stop_hook_idle_behavior()

        if idle_behavior == "ask":
            last_assistant_message = payload.get( "last_assistant_message" )
            cwd                    = payload.get( "cwd" )

            try:
                settings = load_idle_settings()
            except ValueError as e:
                log_to_stream( "stop", {}, extra={
                    "phase" : "idle_settings_invalid",
                    "error" : str( e ),
                } )
                settings = { "enabled": False, "backoff_minutes": [] }

            if settings[ "enabled" ]:
                _arm_idle_waiter( session_id, last_assistant_message, cwd )
                emit_json( {} )  # allow stop; waiter will fire later if still idle
            else:
                result = _ask_anything_else( session_id, last_assistant_message, cwd=cwd )
                emit_json( result )
        elif idle_behavior == "idle_announce":
            persona      = get_voice_persona( session_id )
            persona_name = persona.get( "name" ) if persona else None
            _announce_idle( session_id, persona_name )
            emit_json( {} )  # allow stop — v2.1 owns liveness; this is a courtesy ping
        else:   # "none": silent allow-stop
            emit_json( {} )

if __name__ == "__main__":
    main()
