#!/usr/bin/env python3
"""
Notification Router / Responder for the Notification Proxy Agent.

Receives notification events from the WebSocket listener, determines
if a response is needed, routes to the appropriate strategy (rules
or LLM fallback), and submits the response via REST API.

References:
    - src/cosa/rest/routers/notifications.py (POST /api/notify/response)
    - src/fastapi_app/static/js/notifications.js (submitResponse pattern)
"""

import json
import time
import requests
from typing import Optional

from cosa.agents.notification_proxy.strategies.expediter_rules import ExpediterRuleStrategy
from cosa.agents.notification_proxy.strategies.llm_fallback import LLMFallbackStrategy
from cosa.agents.notification_proxy.strategies.llm_script_matcher import (
    LlmScriptMatcherStrategy, resolve_script_path
)
from cosa.agents.notification_proxy.config import (
    DEFAULT_SERVER_HOST, DEFAULT_SERVER_PORT,
    DEFAULT_STRATEGY, DEFAULT_ACCEPTED_SENDERS,
    NOTIFICATION_PROXY_SCRIPTS_DIR,
    LLM_SCRIPT_MATCHER_SPEC_KEY,
    LLM_SCRIPT_MATCHER_TEMPLATE,
    LLM_SCRIPT_MATCHER_BATCH_TEMPLATE,
)
import cosa.utils.util as cu


class NotificationResponder:
    """
    Routes response-required notifications to the appropriate strategy
    and submits answers via the REST API.

    Requires:
        - At least one strategy is available
        - Lupin server is running for response submission

    Ensures:
        - Notifications that need responses are answered automatically
        - Expediter notifications are answered by rules first, LLM second
        - Non-expediter notifications fall through to LLM
        - All responses are submitted via POST /api/notify/response
    """

    def __init__(
        self,
        profile_name = "deep_research",
        host         = DEFAULT_SERVER_HOST,
        port         = DEFAULT_SERVER_PORT,
        strategy     = DEFAULT_STRATEGY,
        dry_run      = False,
        debug        = False,
        verbose      = False
    ):
        """
        Initialize the responder with a 3-tier strategy chain.

        Requires:
            - profile_name is a valid test profile key
            - strategy is one of: "llm_script", "rules", "auto"

        Ensures:
            - Creates strategies based on the strategy mode:
              - "llm_script": Phi-4 script matcher only (+ cloud fallback)
              - "rules": keyword rules only (+ cloud fallback)
              - "auto": Phi-4 first, rules fallback if vLLM unavailable (+ cloud)
            - Stores server connection info for response submission

        Args:
            profile_name: Test profile for auto-answers
            host: Server hostname for REST API
            port: Server port for REST API
            strategy: Strategy mode ("llm_script", "rules", "auto")
            dry_run: Display notifications without computing answers
            debug: Enable debug output
            verbose: Enable verbose output
        """
        self.host          = host
        self.port          = port
        self.strategy_mode = strategy
        self.dry_run       = dry_run
        self.debug         = debug
        self.verbose       = verbose

        # Extract sender_ids from Q&A script if available
        accepted_senders = DEFAULT_ACCEPTED_SENDERS
        scripts_dir      = cu.get_project_root() + NOTIFICATION_PROXY_SCRIPTS_DIR
        script_path      = resolve_script_path( profile_name, scripts_dir )
        try:
            with open( script_path, "r" ) as f:
                script_data      = json.load( f )
                accepted_senders = script_data.get( "sender_ids", DEFAULT_ACCEPTED_SENDERS )
        except Exception as e:
            if self.debug: print( f"[Responder] Could not load script for sender_ids: {e}" )

        # Always create rule strategy (needed for "rules" and "auto" modes)
        self.rule_strategy = ExpediterRuleStrategy(
            profile_name     = profile_name,
            accepted_senders = accepted_senders,
            debug            = debug,
            verbose          = verbose
        )

        # Create LLM script matcher if requested
        self.script_strategy = None
        if strategy in ( "llm_script", "auto" ):
            try:
                self.script_strategy = LlmScriptMatcherStrategy(
                    script_path          = script_path,
                    llm_spec_key         = LLM_SCRIPT_MATCHER_SPEC_KEY,
                    prompt_template_path = LLM_SCRIPT_MATCHER_TEMPLATE,
                    batch_template_path  = LLM_SCRIPT_MATCHER_BATCH_TEMPLATE,
                    accepted_senders     = accepted_senders,
                    debug                = debug,
                    verbose              = verbose
                )
                if self.debug:
                    print( f"[Responder] LLM script matcher: {'available' if self.script_strategy.available else 'unavailable'}" )
            except Exception as e:
                print( f"[Responder] LLM script matcher init failed: {e}" )
                self.script_strategy = None

        # Cloud LLM fallback (Anthropic SDK)
        self.llm_strategy = LLMFallbackStrategy(
            debug   = debug,
            verbose = verbose
        )

        # Stats
        self.stats = {
            "notifications_received" : 0,
            "responses_sent"         : 0,
            "script_matcher_used"    : 0,
            "rules_used"             : 0,
            "llm_used"               : 0,
            "skipped"                : 0,
            "errors"                 : 0,
        }

    async def handle_event( self, event_type, event_data ):
        """
        Handle a WebSocket event — the main callback for the listener.

        Requires:
            - event_type is a string
            - event_data is a dict

        Ensures:
            - Processes notification_queue_update events
            - Ignores other event types
            - Routes response-required notifications to strategies

        Args:
            event_type: WebSocket event type string
            event_data: Event payload dict
        """
        if event_type == "notification_queue_update":
            await self._handle_notification_update( event_data )

        elif event_type == "job_state_transition":
            if self.verbose:
                job_id     = event_data.get( "job_id", "?" )
                from_queue = event_data.get( "from_queue", "?" )
                to_queue   = event_data.get( "to_queue", "?" )
                print( f"[Responder] Job state: {job_id} {from_queue} → {to_queue}" )

        elif self.verbose:
            print( f"[Responder] Event: {event_type}" )

    async def _handle_notification_update( self, event_data ):
        """
        Process a notification_queue_update event.

        Extracts the notification data, checks if a response is needed,
        routes to a strategy, and submits the answer.

        Requires:
            - event_data has notification details

        Ensures:
            - Only processes notifications where response_requested is True
            - Tries rule strategy first, then LLM fallback
            - Submits response via REST API
            - Logs all actions for debugging

        Args:
            event_data: notification_queue_update event payload
        """
        self.stats[ "notifications_received" ] += 1

        # Extract notification from the event
        # The event may contain the notification directly or nested
        notification = event_data.get( "notification", event_data )

        notification_id    = notification.get( "id_hash" ) or notification.get( "notification_id" ) or notification.get( "id" )
        response_requested = notification.get( "response_requested", False )
        message            = notification.get( "message", "" )
        sender_id          = notification.get( "sender_id", "" )
        response_type      = notification.get( "response_type", "" )
        title              = notification.get( "title", "" )

        # Display notification — Tier 3: debug + verbose (full formatted box)
        if self.debug and self.verbose:
            abstract = notification.get( "abstract", "" )
            print( "" )
            print( "  " + "─" * 54 )
            print( f"  Notification  : {notification_id}" )
            print( "  " + "─" * 54 )
            print( f"  Sender        : {sender_id}" )
            print( f"  Type          : {response_type}" )
            print( f"  Title         : {title}" )
            print( f"  Message       : {message}" )
            if abstract:
                print( f"  Abstract      : {abstract[ :200 ]}" )
            print( "  " + "─" * 54 )

        # Display notification — Tier 2: debug only (truncated)
        elif self.debug:
            print( f"\n[Responder] {'=' * 50}" )
            print( f"[Responder] Notification: {notification_id}" )
            print( f"[Responder] sender_id: {sender_id}" )
            print( f"[Responder] response_type: {response_type}" )
            print( f"[Responder] response_requested: {response_requested}" )
            print( f"[Responder] title: {title}" )
            print( f"[Responder] message: {message[ :120 ]}" )

        # Skip non-response-requested notifications
        if not response_requested:
            self.stats[ "skipped" ] += 1
            if self.verbose: print( f"[Responder] Skipped (no response needed): {title or message[ :50 ]}" )
            return

        if not notification_id:
            self.stats[ "errors" ] += 1
            print( f"[Responder] ERROR: No notification_id in event" )
            return

        # Dry run: display notification, send cancel, skip strategies
        if self.dry_run:
            cancel_value = "no" if response_type == "yes_no" else "cancel"
            self._submit_response( notification_id, cancel_value )
            self.stats[ "skipped" ] += 1

            if self.verbose:
                print( f"  DRY RUN — Declined ({cancel_value} sent)" )
                print( "  " + "─" * 54 )
                print( "" )
            else:
                print( f"[Responder] DRY RUN — Declined ({cancel_value} sent)" )
            return

        # Strategy chain: script matcher → rules (auto mode) → cloud LLM
        answer        = None
        strategy_name = None

        # Tier 1: LLM script matcher (if enabled)
        if answer is None and self.script_strategy is not None and self.script_strategy.can_handle( notification ):
            answer = self.script_strategy.respond( notification )
            if answer is not None:
                strategy_name = "script_matcher"

        # Tier 2: Rule-based strategy (only in "rules" or "auto" mode)
        if answer is None and self.strategy_mode in ( "rules", "auto" ):
            if self.rule_strategy.can_handle( notification ):
                answer = self.rule_strategy.respond( notification )
                if answer is not None:
                    strategy_name = "rules"

        # Tier 3: Cloud LLM fallback
        if answer is None and self.llm_strategy.can_handle( notification ):
            answer = await self.llm_strategy.respond( notification )
            if answer is not None:
                strategy_name = "llm"

        if answer is None:
            self.stats[ "skipped" ] += 1
            print( f"[Responder] No strategy produced an answer for: {title or message[ :50 ]}" )
            return

        # Submit the response
        success = self._submit_response( notification_id, answer )

        if success:
            self.stats[ "responses_sent" ] += 1
            if strategy_name == "script_matcher":
                self.stats[ "script_matcher_used" ] += 1
            elif strategy_name == "rules":
                self.stats[ "rules_used" ] += 1
            elif strategy_name == "llm":
                self.stats[ "llm_used" ] += 1

            display_answer = answer if isinstance( answer, str ) else json.dumps( answer )[ :100 ]

            # Tier 3: verbose answer display
            if self.debug and self.verbose:
                print( f"  ✓ Answered ({strategy_name}):" )
                print( f"  {display_answer}" )
                print( "  " + "─" * 54 )
                print( "" )
            # Tier 1 & 2: existing one-liner
            else:
                print( f"[Responder] ✓ Answered ({strategy_name}): {title or message[ :40 ]} → {display_answer[ :80 ]}" )
        else:
            self.stats[ "errors" ] += 1
            print( f"[Responder] ✗ Failed to submit response for {notification_id}" )

    def _submit_response( self, notification_id, response_value ):
        """
        Submit a response to the Lupin notification API.

        Requires:
            - notification_id is a valid UUID string
            - response_value is a string or dict

        Ensures:
            - POSTs to /api/notify/response
            - Returns True on success (HTTP 200)
            - Returns False on any error
            - Logs the response for debugging

        Args:
            notification_id: UUID of the notification to respond to
            response_value: The answer to submit

        Returns:
            bool: True if response was submitted successfully
        """
        url = f"http://{self.host}:{self.port}/api/notify/response"

        payload = {
            "notification_id" : notification_id,
            "response_value"  : response_value
        }

        try:
            response = requests.post(
                url,
                json    = payload,
                headers = { "Content-Type": "application/json" },
                timeout = 10
            )

            if response.status_code == 200:
                if self.verbose:
                    data = response.json()
                    print( f"[Responder] API response: {data.get( 'status', '?' )} — {data.get( 'message', '' )[ :80 ]}" )
                return True
            else:
                print( f"[Responder] API error: HTTP {response.status_code} — {response.text[ :200 ]}" )
                return False

        except requests.ConnectionError:
            print( f"[Responder] API connection error: server not reachable at {url}" )
            return False
        except requests.Timeout:
            print( f"[Responder] API timeout submitting response" )
            return False
        except Exception as e:
            print( f"[Responder] API error: {e}" )
            return False

    def print_stats( self ):
        """Print summary statistics."""
        print( f"\n{'=' * 50}" )
        print( "Notification Proxy Statistics" )
        print( f"{'=' * 50}" )
        for key, value in self.stats.items():
            label = key.replace( "_", " " ).title()
            print( f"  {label:30s} : {value}" )
        print( f"{'=' * 50}" )


# ============================================================================
# Smoke Test
# ============================================================================

def quick_smoke_test():
    """Quick smoke test for notification responder."""
    print( "\n" + "=" * 60 )
    print( "Notification Responder Smoke Test" )
    print( "=" * 60 )

    tests_passed = 0
    tests_failed = 0

    # Test 1: Construction
    print( "\n1. Testing construction..." )
    try:
        responder = NotificationResponder(
            profile_name = "deep_research",
            debug        = True
        )
        assert responder.rule_strategy is not None
        assert responder.llm_strategy is not None
        print( f"   ✓ Responder constructed (LLM available: {responder.llm_strategy.available})" )
        tests_passed += 1
    except Exception as e:
        print( f"   ✗ Failed: {e}" )
        tests_failed += 1

    # Test 2: Stats initialization
    print( "\n2. Testing stats..." )
    try:
        responder = NotificationResponder( "deep_research" )
        assert responder.stats[ "notifications_received" ] == 0
        assert responder.stats[ "responses_sent" ] == 0
        print( "   ✓ Stats initialized to zero" )
        tests_passed += 1
    except Exception as e:
        print( f"   ✗ Failed: {e}" )
        tests_failed += 1

    # Test 3: Strategy routing
    print( "\n3. Testing strategy routing logic..." )
    try:
        from cosa.agents.notification_proxy.config import DEFAULT_ACCEPTED_SENDERS

        responder = NotificationResponder( "deep_research" )

        # Expediter notification should be handled by rules
        notif = {
            "sender_id"          : DEFAULT_ACCEPTED_SENDERS[ 0 ],
            "response_requested" : True,
            "response_type"      : "yes_no",
            "message"            : "Does this look right?",
            "title"              : "Confirm"
        }
        assert responder.rule_strategy.can_handle( notif )
        answer = responder.rule_strategy.respond( notif )
        assert answer == "yes"
        print( "   ✓ Expediter YES_NO → rules → 'yes'" )

        # Non-expediter should fall through to LLM
        notif2 = {
            "sender_id"          : "some.other@lupin.deepily.ai",
            "response_requested" : True,
            "response_type"      : "open_ended",
            "message"            : "What color?",
            "title"              : "Color"
        }
        assert not responder.rule_strategy.can_handle( notif2 )
        print( "   ✓ Non-expediter falls through rules (LLM would handle)" )

        tests_passed += 1
    except Exception as e:
        print( f"   ✗ Failed: {e}" )
        tests_failed += 1

    # Summary
    print( f"\n{'=' * 60}" )
    print( f"Responder Smoke Test: {tests_passed} passed, {tests_failed} failed" )
    print( "=" * 60 )
    return tests_failed == 0


if __name__ == "__main__":
    success = quick_smoke_test()
    exit( 0 if success else 1 )
