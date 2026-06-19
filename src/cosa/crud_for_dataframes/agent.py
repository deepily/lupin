#!/usr/bin/env python3
"""
CrudForDataFramesAgent — Base agent for voice-driven DataFrame CRUD.

Connects the COSA voice pipeline to Phase 1 CRUD operations via LLM-based
intent extraction. Overrides run_prompt(), run_code(), and run_formatter()
while leaving do_all() untouched so RunningFifoQueue._handle_base_agent()
works unchanged.

Architecture:
    - run_prompt(): Calls LLM, extracts <intent> XML, parses into CRUDIntent
    - run_code(): Dispatches CRUDIntent to crud_operations (error-based fallback)
    - run_formatter(): Formats result for TTS voice output (no extra LLM call)
"""

import cosa.utils.util as du

from cosa.agents.agent_base import AgentBase, CodeGenerationFailedException
from cosa.agents.llm_client_factory import LlmClientFactory

from cosa.crud_for_dataframes.xml_models import CRUDIntent
from cosa.crud_for_dataframes.storage import DataFrameStorage
from cosa.crud_for_dataframes.dispatcher import dispatch, format_result_for_voice, extract_intent_xml
from cosa.crud_for_dataframes.intent_extractor import extract_intent_via_claude_code

from lupin_cli.notifications.notify_user_sync import notify_user_sync
from lupin_cli.notifications.notification_models import NotificationRequest, ResponseType


class CrudForDataFramesAgent( AgentBase ):
    """
    Base agent for voice-driven CRUD operations on per-user DataFrames.

    Extracts intent from natural language via Phi-4 14B (or configured LLM),
    dispatches to crud_operations, and formats results for TTS. Falls back to
    Claude Code headless if the local LLM fails.

    Subclassed by TodoCrudAgent and CalendarCrudAgent for domain-specific
    prompts, schemas, and voice formatting.

    Requires:
        - Configuration keys in lupin-app.ini:
            - llm spec key for agent router go to crud for dataframes
            - prompt template for agent router go to crud for dataframes
            - crud for dataframes output path

    Ensures:
        - do_all() works unchanged with RunningFifoQueue._handle_base_agent()
        - Falls back to Claude Code headless on dispatch errors
        - Raises CodeGenerationFailedException if both paths fail
    """

    def __init__( self, question="", question_gist="", last_question_asked="",
                  push_counter=-1,
                  routing_command="agent router go to crud for dataframes",
                  user_id="ricardo_felipe_ruiz_6bdc", user_email="", session_id="",
                  debug=False, verbose=False, auto_debug=False, inject_bugs=False ):
        """
        Initialize CrudForDataFramesAgent.

        Requires:
            - Either question or last_question_asked is non-empty
            - Config keys exist for the routing_command

        Ensures:
            - self.storage is initialized for per-user parquet I/O
            - self.prompt is built with available lists (XML injected by PromptTemplateProcessor)
            - self.crud_intent is None (set in run_prompt)
        """
        super().__init__(
            df_path_key          = None,
            question             = question,
            question_gist        = question_gist,
            last_question_asked  = last_question_asked,
            push_counter         = push_counter,
            routing_command      = routing_command,
            user_id              = user_id,
            user_email           = user_email,
            session_id           = session_id,
            debug                = debug,
            verbose              = verbose,
            auto_debug           = auto_debug,
            inject_bugs          = inject_bugs
        )

        # Initialize per-user storage
        self.storage = DataFrameStorage(
            user_email = user_email,
            config_mgr = self.config_mgr,
            debug      = debug
        )

        # Build prompt — XML example already injected by PromptTemplateProcessor in super().__init__()
        available_lists = self.storage.get_all_lists_metadata()

        self.prompt = self.prompt_template.format(
            query           = self.last_question_asked,
            available_lists = self._format_lists_for_prompt( available_lists ),
        )

        # CRUDIntent parsed from LLM response (set in run_prompt)
        self.crud_intent = None

        # NO xml_response_tag_names — using CRUDIntent.from_xml() directly

        if self.debug: print( f"CrudForDataFramesAgent: prompt length={len( self.prompt )}, user={user_email}" )

    def run_prompt( self, include_raw_response=False ):
        """
        Execute prompt against configured LLM and parse response into CRUDIntent.

        Overrides AgentBase.run_prompt() to use CRUDIntent.from_xml() directly
        instead of the XmlParserFactory flat-dict intermediate.

        Requires:
            - self.prompt is set to a valid prompt string
            - self.model_name is configured

        Ensures:
            - self.crud_intent is set to a validated CRUDIntent instance
            - self.prompt_response_dict is set for protocol compatibility
            - Returns self.prompt_response_dict
        """
        factory = LlmClientFactory()
        llm     = factory.get_client( self.model_name, debug=self.debug, verbose=self.verbose )

        if self.debug: print( f"CrudForDataFramesAgent.run_prompt: model={self.model_name}, prompt length={len( self.prompt )}" )

        raw_response = llm.run( self.prompt )

        if self.debug: print( f"CrudForDataFramesAgent.run_prompt: raw response length={len( raw_response ) if raw_response else 0}, response:\n{raw_response or '(empty)'}" )

        # Extract <intent> XML and parse into CRUDIntent
        xml_text        = extract_intent_xml( raw_response )
        self.crud_intent = CRUDIntent.from_xml( xml_text, root_tag="intent" )

        if self.debug: print( f"CrudForDataFramesAgent.run_prompt: Parsed intent: operation={self.crud_intent.operation}, target_list={self.crud_intent.target_list}" )

        # Set prompt_response_dict for protocol compatibility with AgentBase
        self.prompt_response_dict = {
            "operation"   : self.crud_intent.operation,
            "target_list" : self.crud_intent.target_list,
            "schema_type" : self.crud_intent.schema_type,
            "confidence"  : self.crud_intent.confidence,
            "raw_response": raw_response if include_raw_response else None,
        }

        return self.prompt_response_dict

    def run_code( self, auto_debug=None, inject_bugs=None ):
        """
        Dispatch CRUDIntent to CRUD operations with error-based fallback.

        Overrides AgentBase.run_code() entirely — no code generation or execution.
        Instead, dispatches the parsed CRUDIntent to crud_operations functions.

        If dispatch fails, falls back to Claude Code headless for intent extraction.
        If both paths fail, raises CodeGenerationFailedException.

        Requires:
            - self.crud_intent is set from run_prompt()

        Ensures:
            - self.code_response_dict is set with return_code and output
            - self.error is None on success
            - Raises CodeGenerationFailedException if all paths fail
        """
        # Voice confirmation for destructive operations
        if self.crud_intent.needs_confirmation():
            confirmed = self._confirm_destructive_operation()
            if not confirmed:
                self.code_response_dict = {
                    "return_code": 0,
                    "output"     : { "status": "cancelled", "message": "Operation cancelled." }
                }
                self.error = None
                return self.code_response_dict

        try:
            result = dispatch( self.crud_intent, self.storage, debug=self.debug )

            if result.get( "status" ) == "error":
                raise ValueError( result[ "message" ] )

            self.code_response_dict = { "return_code": 0, "output": result }
            self.error              = None

        except Exception as e:

            if self.debug: print( f"Phi-4 dispatch failed: {e}. Falling back to Claude Code..." )

            # Build available lists text for fallback prompt
            available_lists_text = self._format_lists_for_prompt( self.storage.get_all_lists_metadata() )
            fallback_intent      = extract_intent_via_claude_code(
                self.last_question_asked,
                available_lists_text,
                debug=self.debug
            )

            if fallback_intent is not None:
                try:
                    result = dispatch( fallback_intent, self.storage, debug=self.debug )

                    if result.get( "status" ) == "error":
                        raise ValueError( result[ "message" ] )

                    self.code_response_dict = { "return_code": 0, "output": result }
                    self.error              = None

                except Exception as fallback_error:
                    raise CodeGenerationFailedException(
                        f"CRUD dispatch failed after Phi-4 and Claude Code: {fallback_error}"
                    )
            else:
                raise CodeGenerationFailedException(
                    f"CRUD dispatch failed: Phi-4 error [{e}], Claude Code returned None"
                )

        return self.code_response_dict

    def run_formatter( self ):
        """
        Format CRUD result for TTS voice output.

        Overrides AgentBase.run_formatter() to use format_result_for_voice()
        directly instead of the RawOutputFormatter LLM call.

        Requires:
            - self.code_response_dict contains 'output' with CRUD result dict
            - self.crud_intent is set with the operation

        Ensures:
            - self.answer_conversational is set to a TTS-friendly string
            - self.answer is set for QueueableJob protocol compatibility
            - Returns self.answer_conversational
        """
        result    = self.code_response_dict[ "output" ]
        operation = self.crud_intent.operation

        # Handle cancelled operations (user denied destructive confirmation)
        if result.get( "status" ) == "cancelled":
            self.answer_conversational = result.get( "message", "Operation cancelled." )
            self.answer                = self.answer_conversational
            if self.debug: print( f"CrudForDataFramesAgent.run_formatter: cancelled — {self.answer_conversational}" )
            return self.answer_conversational

        self.answer_conversational = format_result_for_voice( result, operation )
        self.answer                = self.answer_conversational

        if self.debug: print( f"CrudForDataFramesAgent.run_formatter: {self.answer_conversational}" )

        return self.answer_conversational

    def restore_from_serialized_state( self, file_path ):
        """
        Restore agent from serialized state.

        Requires:
            - file_path is a valid path

        Raises:
            - NotImplementedError (not implemented for CRUD agents)
        """
        raise NotImplementedError( "CrudForDataFramesAgent.restore_from_serialized_state() not implemented" )

    def _format_lists_for_prompt( self, metadata ):
        """
        Format list metadata for inclusion in the LLM prompt.

        Requires:
            - metadata is a list of dicts with schema_type, list_name, row_count

        Ensures:
            - Returns a formatted string describing user's lists
            - Returns "(no lists yet)" if metadata is empty
        """
        if not metadata:
            return "(no lists yet)"

        lines = []
        for entry in metadata:
            lines.append( f"- {entry[ 'list_name' ]} ({entry[ 'schema_type' ]}, {entry[ 'row_count' ]} items)" )

        return "\n".join( lines )

    def _confirm_destructive_operation( self ):
        """
        Ask user for voice confirmation before executing a destructive operation.

        Uses notify_user_sync with YES_NO response type, matching the pattern
        from _confirm_agentic_routing in todo_fifo_queue.py.

        Requires:
            - self.crud_intent is a valid CRUDIntent with a destructive operation
            - self.user_email is set for notification routing

        Ensures:
            - Returns True if user confirms (says yes)
            - Returns False on denial, timeout, or error (safe default)
        """
        operation   = self.crud_intent.operation
        target_list = self.crud_intent.target_list or "your list"

        message = f"Are you sure you want to {operation} from {target_list}?"

        if self.debug: print( f"CrudForDataFramesAgent._confirm_destructive_operation: {message}" )

        request = NotificationRequest(
            message         = message,
            response_type   = ResponseType.YES_NO,
            target_user     = self.user_email,
            timeout_seconds = 30,
            sender_id       = "crud.agent@lupin.deepily.ai",
            priority        = "high",
            suppress_ding   = True,
            response_default = "no"
        )

        response = notify_user_sync( request, debug=self.debug )

        if response.is_timeout or response.is_error:
            if self.debug: print( f"Confirmation timeout/error — defaulting to cancel" )
            return False

        selected = response.response_value
        if self.debug: print( f"User confirmation response: [{selected}]" )

        return selected is not None and selected.strip().lower().startswith( "yes" )


def quick_smoke_test():
    """Module-level smoke test following CoSA convention."""

    print( "Testing CrudForDataFramesAgent module..." )
    passed = True

    try:
        # Test _format_lists_for_prompt (static-ish, testable without full init)
        # We can't easily test the full agent without a running LLM,
        # so we test the utility method and constructor separately

        # Test with empty metadata
        agent_cls = CrudForDataFramesAgent
        # Use a mock-like approach: test the static method behavior
        result = CrudForDataFramesAgent._format_lists_for_prompt( None, [] )
        assert result == "(no lists yet)"
        print( "  ✓ _format_lists_for_prompt: empty metadata" )

        result = CrudForDataFramesAgent._format_lists_for_prompt( None, [
            { "schema_type": "todo", "list_name": "groceries", "row_count": 3 },
            { "schema_type": "calendar", "list_name": "meetings", "row_count": 5 },
        ] )
        assert "groceries" in result
        assert "meetings" in result
        assert "3 items" in result
        print( f"  ✓ _format_lists_for_prompt: formatted metadata" )

        print( "  ○ Full agent constructor: requires config + LLM (tested in unit tests)" )

        print( "✓ CrudForDataFramesAgent module smoke test PASSED" )

    except Exception as e:
        print( f"✗ CrudForDataFramesAgent module smoke test FAILED: {e}" )
        import traceback
        traceback.print_exc()
        passed = False

    return passed


if __name__ == "__main__":
    success = quick_smoke_test()
    exit( 0 if success else 1 )
