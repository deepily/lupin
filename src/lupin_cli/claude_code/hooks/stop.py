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
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_cli.claude_code.hooks.lib.hook_common import (
    read_hook_input, log_payload, log_to_stream, emit_json, send_tts,
    drain_and_acknowledge, format_voice_context, build_stop_block,
    build_stop_block_with_system_message,
    enrich_voice_context, get_stop_block_count, increment_stop_block_count,
    reset_stop_block_count, MAX_STOP_BLOCKS
)
from lupin_cli.claude_code.hooks.lib.session_bridge import (
    get_claude_session_id, build_sender_id_for_cc
)
from lupin_cli.notifications.notify_user_sync import notify_user_sync
from lupin_cli.notifications.notification_models import (
    NotificationRequest, ResponseType, NotificationPriority
)
from cosa.utils.notification_utils import (
    extract_qualifier_comment, format_qualified_response
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
        gist   = gister.get_gist( last_assistant_message )
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


def _ask_anything_else( session_id, last_assistant_message=None ):
    """
    Ask the user "Anything else?" via notify_user_sync with a 5-minute timeout.

    Returns the stop hook JSON to emit: block dict if user wants to continue,
    empty dict if user says no / timeout / error.

    Requires:
        - session_id is a string for sender_id resolution
        - last_assistant_message is a string or None

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
            message = f"[LUPIN] I'm finished *{gist}*. Is there anything else you want me to do?"
        else:
            message = "[LUPIN] I've finished the current task. Is there anything else you'd like me to do?"

        request = NotificationRequest(
            message                  = message,
            response_type            = ResponseType.YES_NO,
            priority                 = NotificationPriority.HIGH,
            timeout_seconds          = 300,
            response_default         = "no",
            title                    = "Continue Session?",
            sender_id                = sender_id,
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
                system_msg = format_qualified_response( answer, qualifier )
                log_to_stream( "stop", {}, extra={
                    "phase"  : "qualifier_block",
                    "answer" : answer,
                    "reason" : f"User qualifier: {qualifier}"[ :120 ]
                } )
                return build_stop_block_with_system_message( f"User qualifier: {qualifier}", system_msg )
            else:
                reason = "The user wants to continue working. Ask them what they'd like done next."
                log_to_stream( "stop", {}, extra={
                    "phase"  : "qualifier_block",
                    "answer" : answer,
                    "reason" : reason[ :120 ]
                } )
                return build_stop_block( reason )

        if answer == "no" and qualifier:
            system_msg = format_qualified_response( answer, qualifier )
            log_to_stream( "stop", {}, extra={
                "phase"  : "qualifier_block",
                "answer" : answer,
                "reason" : f"User qualifier: {qualifier}"[ :120 ]
            } )
            return build_stop_block_with_system_message( f"User qualifier: {qualifier}", system_msg )

        # Plain "no", timeout, error → allow stop
        return {}

    except Exception as e:
        # Server down, network error, import error → allow stop gracefully
        send_tts( f"Stop — notify error: {e}" )
        return {}


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
    session_id = payload.get( "session_id", "" ) or get_claude_session_id()

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
        # No voice input → Phase 2: ask user "Anything else?" via notification
        reset_stop_block_count( session_id )
        last_assistant_message = payload.get( "last_assistant_message" )
        result = _ask_anything_else( session_id, last_assistant_message )
        emit_json( result )


if __name__ == "__main__":
    main()
