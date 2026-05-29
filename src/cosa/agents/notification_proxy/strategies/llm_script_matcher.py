#!/usr/bin/env python3
"""
LLM-based response strategy using Q&A scripts and Phi-4 fuzzy matching.

Replaces brittle keyword matching (ExpediterRuleStrategy) with local Phi-4
inference. The proxy receives a Q&A script (question-answer pairs) and uses
Phi-4 to fuzzy-match incoming questions to script entries, returning the
scripted answer.

References:
    - src/conf/notification-proxy-scripts/ (Q&A script format and README)
    - src/conf/notification-proxy-scripts/_template.json (starter template)
    - src/cosa/agents/notification_proxy/xml_models.py (ScriptMatcherResponse)
"""

import json
import os
from typing import Optional

import cosa.utils.util as cu
from cosa.agents.llm_client_factory import LlmClientFactory
from cosa.agents.notification_proxy.config import DEFAULT_ACCEPTED_SENDERS
from cosa.agents.notification_proxy.xml_models import ScriptMatcherResponse, BatchScriptMatcherResponse
from cosa.agents.io_models.utils.prompt_template_processor import PromptTemplateProcessor


class LlmScriptMatcherStrategy:
    """
    LLM-based auto-responder using Q&A scripts and Phi-4 fuzzy matching.

    Loads a Q&A script at construction time and uses Phi-4 to semantically
    match incoming notification questions to script entries. All response
    types (YES_NO, OPEN_ENDED, OPEN_ENDED_BATCH, MULTIPLE_CHOICE) go
    through the LLM.

    Requires:
        - script_path points to a valid JSON file following the Q&A script format
        - See src/conf/notification-proxy-scripts/README.md for format specification
        - See src/conf/notification-proxy-scripts/_template.json for starter template
        - vLLM server is running with Phi-4 model loaded

    Ensures:
        - can_handle() returns True for expediter notifications needing a response
        - respond() returns a string answer or None
        - Falls through gracefully if LLM is unavailable
    """

    def __init__(
        self,
        script_path,
        llm_spec_key           = "kaitchup/phi_4_14b",
        prompt_template_path   = "/src/conf/prompts/notification-proxy-script-matcher.txt",
        batch_template_path    = "/src/conf/prompts/notification-proxy-batch-matcher.txt",
        accepted_senders       = None,
        debug                  = False,
        verbose                = False
    ):
        """
        Initialize with a Q&A script and LLM configuration.

        Requires:
            - script_path is a path to a valid Q&A script JSON file
            - llm_spec_key is a valid model key in LlmClientFactory

        Ensures:
            - Loads the Q&A script entries
            - Extracts accepted_senders from script (or uses parameter/default)
            - Creates LLM client and prompt template processor
            - Sets available=True if LLM client can be created
            - Raises FileNotFoundError if script file does not exist

        Args:
            script_path: Absolute path to Q&A script JSON file
            llm_spec_key: Model identifier for LlmClientFactory
            prompt_template_path: Path (relative to project root) for single-question template
            batch_template_path: Path (relative to project root) for batch template
            accepted_senders: List of sender ID prefixes to accept (overrides script field)
            debug: Enable debug output
            verbose: Enable verbose output
        """
        self.debug               = debug
        self.verbose             = verbose
        self.llm_spec_key        = llm_spec_key
        self.prompt_template_path = prompt_template_path
        self.batch_template_path  = batch_template_path
        self._available          = False
        self._client             = None
        self._script             = None
        self._entries            = []

        # Load the Q&A script
        if not os.path.exists( script_path ):
            raise FileNotFoundError( f"Q&A script not found: {script_path}" )

        with open( script_path, "r" ) as f:
            self._script = json.load( f )

        self._entries = self._script.get( "entries", [] )

        # Resolve accepted senders: parameter > script field > default
        if accepted_senders is not None:
            self.accepted_senders = accepted_senders
        else:
            self.accepted_senders = self._script.get( "sender_ids", DEFAULT_ACCEPTED_SENDERS )

        if self.debug:
            profile = self._script.get( "profile_name", "?" )
            print( f"[LlmScriptMatcher] Loaded script '{profile}' with {len( self._entries )} entries" )

        # Create LLM client
        try:
            factory = LlmClientFactory( debug=debug, verbose=verbose )
            self._client = factory.get_client( llm_spec_key, debug=debug, verbose=verbose )
            self._available = True
            if self.debug: print( f"[LlmScriptMatcher] LLM client ready ({llm_spec_key})" )
        except Exception as e:
            print( f"[LlmScriptMatcher] LLM client unavailable: {e}" )
            self._available = False

        # Prompt template processor
        self._processor = PromptTemplateProcessor( debug=debug, verbose=verbose )

    @property
    def available( self ):
        """Whether the LLM client is available for inference."""
        return self._available

    def can_handle( self, notification ):
        """
        Check if this strategy can handle the notification.

        Requires:
            - notification is a dict with at least 'sender_id' and 'response_requested'

        Ensures:
            - Returns True if sender matches any accepted sender prefix,
              response is requested, and LLM client is available
            - Returns False otherwise

        Args:
            notification: Notification event data dict

        Returns:
            bool: True if this strategy should handle this notification
        """
        if not self._available:
            return False

        sender_id          = notification.get( "sender_id", "" )
        response_requested = notification.get( "response_requested", False )

        if not response_requested:
            return False

        # Check sender against accepted list (prefix match, ignoring #suffix)
        sender_base = sender_id.split( "#" )[ 0 ]
        is_accepted = any( sender_base == prefix for prefix in self.accepted_senders )

        return is_accepted

    def respond( self, notification ):
        """
        Generate a response using LLM fuzzy matching against the Q&A script.

        Requires:
            - notification is a dict with 'message', 'response_type', etc.
            - can_handle( notification ) returned True

        Ensures:
            - Returns string answer for matched entries
            - Returns JSON string for OPEN_ENDED_BATCH
            - Returns None if no match found or LLM error

        Args:
            notification: Notification event data dict

        Returns:
            str or None: The auto-answer, or None if no match
        """
        if not self._available:
            return None

        response_type = notification.get( "response_type", "" )

        if response_type == "open_ended_batch":
            return self._handle_batch( notification )
        else:
            return self._handle_single( notification, response_type )

    def _handle_single( self, notification, response_type ):
        """
        Handle a single-question notification (YES_NO, OPEN_ENDED, MULTIPLE_CHOICE).

        Requires:
            - notification has 'message', 'title', 'response_type'
            - response_type is one of: yes_no, open_ended, multiple_choice

        Ensures:
            - Returns the matched answer string, or None

        Args:
            notification: Notification event data dict
            response_type: The response type string

        Returns:
            str or None: The answer or None
        """
        message = notification.get( "message", "" )
        title   = notification.get( "title", "" )

        # Filter entries by agent context if available
        entries = self._filter_entries_by_agent( notification )

        # Build options section for MULTIPLE_CHOICE
        options_section = ""
        if response_type == "multiple_choice":
            options_section = self._format_options( notification )

        # Format script entries for the prompt
        formatted_entries = self._format_entries( entries )

        # Load and process prompt template
        template_raw = cu.get_file_as_string(
            cu.get_project_root() + self.prompt_template_path
        )
        template_processed = self._processor.process_template(
            template_raw, "notification proxy script matcher"
        )

        # Fill runtime placeholders
        prompt = template_processed.format(
            response_type     = response_type,
            title             = title,
            incoming_question = message,
            options_section   = options_section,
            script_entries    = formatted_entries
        )

        if self.debug and self.verbose:
            print( f"[LlmScriptMatcher] Prompt length: {len( prompt )} chars" )

        # Send to LLM
        try:
            response_text = self._client.run( prompt )
            if self.debug: print( f"[LlmScriptMatcher] Raw response: {response_text[ :200 ]}" )

            parsed = ScriptMatcherResponse.from_xml( response_text )

            if parsed.is_match():
                if self.debug:
                    print( f"[LlmScriptMatcher] Match: entry={parsed.matched_entry}, "
                           f"confidence={parsed.confidence}, answer={parsed.answer[ :80 ]}" )
                return parsed.answer
            else:
                if self.debug: print( f"[LlmScriptMatcher] No match (reasoning: {parsed.reasoning[ :100 ]})" )
                return None

        except Exception as e:
            print( f"[LlmScriptMatcher] LLM error: {e}" )
            return None

    def _handle_batch( self, notification ):
        """
        Handle an OPEN_ENDED_BATCH notification using a single LLM call.

        Requires:
            - notification has 'response_options' with 'questions' list

        Ensures:
            - Returns JSON string with {"answers": {...}} on success
            - Returns None on failure

        Args:
            notification: Notification event data dict

        Returns:
            str or None: JSON string with answers dict, or None
        """
        options   = notification.get( "response_options", {} )
        questions = options.get( "questions", [] )

        if not questions:
            if self.debug: print( "[LlmScriptMatcher] BATCH: no questions found" )
            return None

        # Filter entries by agent context
        entries = self._filter_entries_by_agent( notification )

        # Format batch questions
        batch_lines = []
        for i, q in enumerate( questions ):
            header   = q.get( "header", f"Q{i}" )
            question = q.get( "question", "" )
            default  = q.get( "default_value", "" )
            batch_lines.append(
                f"  {i + 1}. Header: \"{header}\" | Question: \"{question}\" | Default: \"{default}\""
            )
        batch_questions = "\n".join( batch_lines )

        # Format script entries
        formatted_entries = self._format_entries( entries )

        # Load and process batch template
        template_raw = cu.get_file_as_string(
            cu.get_project_root() + self.batch_template_path
        )
        template_processed = self._processor.process_template(
            template_raw, "notification proxy batch script matcher"
        )

        # Fill runtime placeholders
        prompt = template_processed.format(
            batch_questions = batch_questions,
            script_entries  = formatted_entries
        )

        if self.debug and self.verbose:
            print( f"[LlmScriptMatcher] Batch prompt length: {len( prompt )} chars" )

        # Send to LLM
        try:
            response_text = self._client.run( prompt )
            if self.debug: print( f"[LlmScriptMatcher] Batch raw response: {response_text[ :200 ]}" )

            parsed = BatchScriptMatcherResponse.from_xml( response_text )

            if parsed.is_match():
                answers = parsed.get_answers_dict()
                if answers:
                    if self.debug: print( f"[LlmScriptMatcher] Batch answers: {answers}" )
                    return json.dumps( { "answers": answers } )

                if self.debug: print( "[LlmScriptMatcher] Batch: entries parsed but no answers extracted" )
                return None
            else:
                if self.debug: print( f"[LlmScriptMatcher] Batch: no match" )
                return None

        except Exception as e:
            print( f"[LlmScriptMatcher] Batch LLM error: {e}" )
            return None

    def _filter_entries_by_agent( self, notification ):
        """
        Filter script entries by agent context from notification abstract.

        Requires:
            - notification may have 'abstract' field with agent info

        Ensures:
            - Returns entries scoped to the detected agent + universal entries
            - Returns all entries if no agent context is detected

        Args:
            notification: Notification event data dict

        Returns:
            list: Filtered script entries
        """
        abstract = notification.get( "abstract", "" )

        # Try to extract agent name from abstract
        agent_name = None
        if abstract:
            # Look for "Agent: <name>" pattern
            for line in abstract.split( "\n" ):
                line_lower = line.strip().lower()
                if line_lower.startswith( "agent:" ) or line_lower.startswith( "**agent**:" ):
                    agent_part = line.split( ":", 1 )[ 1 ].strip().strip( "*" ).strip()
                    # Normalize to snake_case
                    agent_name = agent_part.lower().replace( " ", "_" ).replace( "-", "_" )
                    break

        if not agent_name:
            # No agent context — return all entries
            return self._entries

        if self.debug: print( f"[LlmScriptMatcher] Agent context: {agent_name}" )

        # Filter: entries with no agents tag (universal) + entries tagged for this agent
        filtered = []
        for entry in self._entries:
            agents_tag = entry.get( "agents" )
            if agents_tag is None:
                filtered.append( entry )
            elif agent_name in agents_tag:
                filtered.append( entry )

        if self.debug:
            print( f"[LlmScriptMatcher] Filtered {len( self._entries )} → {len( filtered )} entries for agent '{agent_name}'" )

        return filtered

    def _format_entries( self, entries ):
        """
        Format script entries for prompt injection.

        Requires:
            - entries is a list of script entry dicts

        Ensures:
            - Returns a human-readable numbered list of entries

        Args:
            entries: List of script entry dicts

        Returns:
            str: Formatted entries text
        """
        lines = []
        for i, entry in enumerate( entries ):
            question = entry.get( "question_pattern", "" )
            answer   = entry.get( "answer", "" )
            arg      = entry.get( "arg_name", "" )
            lines.append( f"  [{i}] Question: \"{question}\" | Answer: \"{answer}\" | Arg: {arg}" )

        return "\n".join( lines )

    def _format_options( self, notification ):
        """
        Format MULTIPLE_CHOICE options for prompt injection.

        Requires:
            - notification has 'response_options' with 'questions' list

        Ensures:
            - Returns formatted options text, or empty string if none

        Args:
            notification: Notification event data dict

        Returns:
            str: Formatted options section
        """
        options   = notification.get( "response_options", {} )
        questions = options.get( "questions", [] )

        if not questions:
            return ""

        lines = [ "Available options:" ]
        for q in questions:
            for opt in q.get( "options", [] ):
                label = opt.get( "label", "" )
                desc  = opt.get( "description", "" )
                if desc:
                    lines.append( f'  - "{label}" — {desc}' )
                else:
                    lines.append( f'  - "{label}"' )

        return "\n".join( lines )


# ============================================================================
# Script Path Resolution
# ============================================================================

def resolve_script_path( profile_name, scripts_dir=None ):
    """
    Resolve Q&A script file path from profile name.

    Requires:
        - profile_name is a string

    Ensures:
        - Returns absolute path to the script file
        - Script file name derived from profile_name: underscores → dashes + .json

    Args:
        profile_name: Test profile name (e.g., "deep_research")
        scripts_dir: Override for scripts directory (default: from config)

    Returns:
        str: Absolute path to the script JSON file
    """
    if scripts_dir is None:
        scripts_dir = cu.get_project_root() + "/src/conf/notification-proxy-scripts"

    script_file = profile_name.replace( "_", "-" ) + ".json"
    return os.path.join( scripts_dir, script_file )


# ============================================================================
# Smoke Test
# ============================================================================

def quick_smoke_test():
    """Quick smoke test for LLM script matcher strategy."""
    print( "\n" + "=" * 60 )
    print( "LLM Script Matcher Strategy Smoke Test" )
    print( "=" * 60 )

    tests_passed = 0
    tests_failed = 0

    # Test 1: Script path resolution
    print( "\n1. Testing script path resolution..." )
    try:
        path = resolve_script_path( "deep_research" )
        assert path.endswith( "deep-research.json" )
        assert os.path.exists( path ), f"Script file not found: {path}"
        print( f"   ✓ deep_research → {path}" )

        path = resolve_script_path( "all_agents" )
        assert path.endswith( "all-agents.json" )
        print( f"   ✓ all_agents → {path}" )

        tests_passed += 1
    except Exception as e:
        print( f"   ✗ Failed: {e}" )
        tests_failed += 1

    # Test 2: Script loading
    print( "\n2. Testing script loading..." )
    try:
        script_path = resolve_script_path( "deep_research" )
        with open( script_path, "r" ) as f:
            script = json.load( f )
        assert "entries" in script
        assert len( script[ "entries" ] ) >= 3
        print( f"   ✓ Loaded {len( script[ 'entries' ] )} entries from deep-research.json" )

        tests_passed += 1
    except Exception as e:
        print( f"   ✗ Failed: {e}" )
        tests_failed += 1

    # Test 3: Construction (may fail if vLLM unavailable — that's OK)
    print( "\n3. Testing construction..." )
    try:
        script_path = resolve_script_path( "deep_research" )
        strategy = LlmScriptMatcherStrategy(
            script_path = script_path,
            debug       = True,
            verbose     = False
        )
        print( f"   ✓ Constructed (LLM available: {strategy.available})" )
        tests_passed += 1
    except FileNotFoundError as e:
        print( f"   ✗ Script not found: {e}" )
        tests_failed += 1
    except Exception as e:
        print( f"   ⚠ Construction warning (LLM may be unavailable): {e}" )
        tests_passed += 1

    # Test 4: can_handle
    print( "\n4. Testing can_handle..." )
    try:
        script_path = resolve_script_path( "deep_research" )
        strategy = LlmScriptMatcherStrategy( script_path=script_path, debug=False )

        if strategy.available:
            assert strategy.can_handle( {
                "sender_id"          : DEFAULT_ACCEPTED_SENDERS[ 0 ],
                "response_requested" : True
            } )
            print( "   ✓ Handles expediter notifications" )

            assert not strategy.can_handle( {
                "sender_id"          : "claude.code@lupin.deepily.ai",
                "response_requested" : True
            } )
            print( "   ✓ Rejects non-expediter notifications" )
        else:
            print( "   ⚠ LLM unavailable — can_handle returns False (expected)" )

        tests_passed += 1
    except Exception as e:
        print( f"   ✗ Failed: {e}" )
        tests_failed += 1

    # Test 5: Entry filtering
    print( "\n5. Testing entry filtering..." )
    try:
        script_path = resolve_script_path( "all_agents" )
        strategy = LlmScriptMatcherStrategy( script_path=script_path, debug=True )

        # With agent context
        notification = {
            "abstract" : "**Agent**: Deep Research\nJob ID: test-123"
        }
        filtered = strategy._filter_entries_by_agent( notification )
        print( f"   ✓ Filtered for deep_research: {len( filtered )} entries" )

        # Without agent context
        notification = { "abstract": "" }
        unfiltered = strategy._filter_entries_by_agent( notification )
        assert len( unfiltered ) == len( strategy._entries )
        print( f"   ✓ No agent context: {len( unfiltered )} entries (all)" )

        tests_passed += 1
    except Exception as e:
        print( f"   ✗ Failed: {e}" )
        tests_failed += 1

    # Summary
    print( f"\n{'=' * 60}" )
    print( f"LLM Script Matcher Smoke Test: {tests_passed} passed, {tests_failed} failed" )
    print( "=" * 60 )
    return tests_failed == 0


if __name__ == "__main__":
    success = quick_smoke_test()
    exit( 0 if success else 1 )
