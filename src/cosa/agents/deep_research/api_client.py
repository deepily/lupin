#!/usr/bin/env python3
"""
Direct Anthropic API Client for COSA Deep Research Agent.

Provides async wrapper for Claude API with:
- Model selection (Opus for lead, Sonnet for subagents)
- Web search tool integration
- Extended thinking support
- Structured JSON output
- Per-request cost tracking

Design Principles:
- Async-first for parallel subagent execution
- Integrated cost tracking via CostTracker
- Configurable model selection per call type
- Graceful error handling with retries
"""

import os
import json
import asyncio
import logging
from typing import Optional, Any, Literal
from dataclasses import dataclass, field

try:
    import anthropic
    from anthropic import AsyncAnthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    AsyncAnthropic = None

from .config import ResearchConfig
from .cost_tracker import CostTracker, BudgetExceededError
from .rate_limiter import WebSearchRateLimiter

logger = logging.getLogger( __name__ )


# =============================================================================
# API Key Configuration - FIREWALL PATTERN
# =============================================================================
# NEVER use ANTHROPIC_API_KEY - that is reserved for Claude Code CLI
# Using the same env var could cause billing confusion or conflicts
#
# Priority order for key retrieval:
#   1. Explicit api_key parameter (highest priority)
#   2. Environment variable ANTHROPIC_API_KEY_FIREWALLED (testing/production)
#   3. Local file via cu.get_api_key() (development)
# =============================================================================

# Environment variable name for testing/production deployments
ENV_VAR_NAME = "ANTHROPIC_API_KEY_FIREWALLED"

# Local file name for development (in src/conf/keys/)
KEY_FILE_NAME = "anthropic-api-key-firewalled"


# Web search tool definition for Anthropic API
WEB_SEARCH_TOOL = {
    "type" : "web_search_20250305",
    "name" : "web_search",
    # Configuration options can be added here
}


@dataclass
class APIResponse:
    """
    Structured response from an API call.

    Contains the response content, usage data, and any tool results.
    """
    content        : str
    model          : str
    input_tokens   : int
    output_tokens  : int
    stop_reason    : str
    tool_use       : list = field( default_factory=list )
    search_results : list = field( default_factory=list )
    raw_response   : Any = None


class ResearchAPIClient:
    """
    Async Anthropic API client for deep research.

    Requires:
        - anthropic SDK is installed
        - One of the following API key sources:
          1. api_key parameter (explicit)
          2. ANTHROPIC_API_KEY_FIREWALLED environment variable (testing/production)
          3. src/conf/keys/anthropic-api-key-firewalled file (development)

    Note:
        NEVER uses ANTHROPIC_API_KEY - that is reserved for Claude Code CLI.
        Uses the firewalled pattern to prevent billing confusion.

    Ensures:
        - Async execution for parallel subagent support
        - Integrated cost tracking
        - Web search tool access
        - Model-appropriate routing (Opus for lead, Sonnet for subagents)
    """

    def __init__(
        self,
        config: Optional[ ResearchConfig ] = None,
        cost_tracker: Optional[ CostTracker ] = None,
        api_key: Optional[ str ] = None,
        debug: bool = False,
        verbose: bool = False
    ):
        """
        Initialize the API client.

        Args:
            config: Research configuration (uses defaults if None)
            cost_tracker: Cost tracker for usage recording (optional)
            api_key: Anthropic API key (uses env var if None)
            debug: Enable debug output
            verbose: Enable verbose output
        """
        if not ANTHROPIC_AVAILABLE:
            raise ImportError(
                "anthropic SDK not installed. "
                "Install with: pip install anthropic"
            )

        self.config       = config or ResearchConfig()
        self.cost_tracker = cost_tracker
        self.debug        = debug
        self.verbose      = verbose

        # Get API key using firewalled pattern
        # Priority: 1) Explicit parameter, 2) Env var (prod), 3) Local file (dev)
        self.api_key    = api_key
        self.key_source = "parameter"

        if not self.api_key:
            # Try environment variable (testing/production)
            self.api_key = os.environ.get( ENV_VAR_NAME )
            self.key_source = "environment"

        if not self.api_key:
            # Fall back to local file (development)
            try:
                import cosa.utils.util as cu
                self.api_key = cu.get_api_key( KEY_FILE_NAME )
                self.key_source = "local file"
            except Exception as e:
                if self.debug:
                    print( f"[ResearchAPIClient] Could not load local key file: {e}" )

        if not self.api_key:
            raise ValueError(
                f"Anthropic API key not found. Either:\n"
                f"  1. Pass api_key parameter\n"
                f"  2. Set {ENV_VAR_NAME} environment variable (testing/production)\n"
                f"  3. Create src/conf/keys/{KEY_FILE_NAME} file (development)"
            )

        # Initialize async client
        self._client = AsyncAnthropic( api_key=self.api_key )

        # Initialize rate limiter for web search calls
        # Get configuration from ConfigurationManager
        try:
            from cosa.config.configuration_manager import ConfigurationManager
            config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )

            tokens_per_minute = config_mgr.get(
                "deep research web search tokens per minute", 30_000, return_type="int"
            )
            window_seconds = config_mgr.get(
                "deep research web search window seconds", 60.0, return_type="float"
            )
            notify_threshold = config_mgr.get(
                "deep research rate limit notify threshold", 5.0, return_type="float"
            )
        except Exception as e:
            # Fall back to defaults if ConfigurationManager unavailable
            if self.debug:
                print( f"[ResearchAPIClient] ConfigurationManager unavailable, using defaults: {e}" )
            tokens_per_minute = 30_000
            window_seconds    = 60.0
            notify_threshold  = 5.0

        self._rate_limiter = WebSearchRateLimiter(
            tokens_per_minute = tokens_per_minute,
            window_seconds    = window_seconds,
            notify_threshold  = notify_threshold,
            notify_callback   = self._rate_limit_notify,
            debug             = debug,
        )

        if self.debug:
            print( f"[ResearchAPIClient] API key source: {self.key_source}" )
            print( f"[ResearchAPIClient] Initialized with models: lead={self.config.lead_model}, subagent={self.config.subagent_model}" )
            print( f"[ResearchAPIClient] Rate limiter: {tokens_per_minute:,} tokens/min, {window_seconds}s window" )

    async def _rate_limit_notify( self, message: str, priority: str ) -> None:
        """
        Callback for rate limiter to notify user about delays.

        Uses voice_io if available, otherwise prints to console.

        Args:
            message: Notification message
            priority: Notification priority (low, medium, high)
        """
        try:
            from . import voice_io
            await voice_io.notify( message, priority=priority )
        except Exception as e:
            # Fall back to console if voice_io unavailable
            if self.debug:
                print( f"[ResearchAPIClient] Rate limit notification: {message}" )

    def get_rate_limiter( self ) -> WebSearchRateLimiter:
        """Get the rate limiter instance for external access (e.g., CLI progress reporting)."""
        return self._rate_limiter

    async def call_lead_agent(
        self,
        system_prompt: str,
        user_message: str,
        call_type: str = "lead",
        use_extended_thinking: bool = False,
        max_tokens: int = 4096,
        temperature: float = 1.0
    ) -> APIResponse:
        """
        Call the lead agent (uses Opus model).

        Lead agent handles planning, synthesis, and coordination tasks.

        Args:
            system_prompt: System prompt for the agent
            user_message: User message/query
            call_type: Type of call for cost tracking
            use_extended_thinking: Enable extended thinking
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature

        Returns:
            APIResponse: Structured response with content and usage
        """
        return await self._call_api(
            model             = self.config.lead_model,
            system_prompt     = system_prompt,
            user_message      = user_message,
            call_type         = call_type,
            use_web_search    = False,  # Lead agent typically doesn't search
            use_extended_thinking = use_extended_thinking,
            max_tokens        = max_tokens,
            temperature       = temperature,
        )

    async def call_subagent(
        self,
        system_prompt: str,
        user_message: str,
        subquery_index: int,
        call_type: str = "research",
        use_web_search: bool = True,
        max_tokens: int = 4096,
        temperature: float = 1.0
    ) -> APIResponse:
        """
        Call a research subagent (uses Sonnet model).

        Subagents handle focused research tasks with web search.
        Includes rate limiting for web search calls to stay within
        Anthropic's 30,000 tokens/minute limit.

        Args:
            system_prompt: System prompt for the subagent
            user_message: The subquery to research
            subquery_index: Index of this subquery (for tracking)
            call_type: Type of call for cost tracking
            use_web_search: Enable web search tool
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature

        Returns:
            APIResponse: Structured response with content and search results
        """
        # Rate limit check BEFORE making web search calls.
        # Phase 3 (v0.1.7 CJ Flow async multi-lane): route through ApiResourceManager
        # singleton rather than the api_client's own _rate_limiter instance. ARM
        # wraps WebSearchRateLimiter internally — runtime behaviour is identical,
        # but provider state is observable via /api/queue/pool-status and any
        # future per-provider contention logic applies uniformly across callers.
        # Falls back to the local _rate_limiter if ARM is not initialised (e.g.,
        # unit tests or pre-startup contexts) — matches legacy behaviour exactly.
        if use_web_search:
            try:
                from cosa.utils.api_resource_manager import get_arm
                await get_arm().acquire( provider="anthropic_web_search" )
            except RuntimeError:
                # ARM not initialised (unit tests / pre-startup) — fall back to
                # local limiter for unchanged behaviour.
                delay = await self._rate_limiter.wait_if_needed()
                if self.debug and delay > 0:
                    print( f"[ResearchAPIClient] (ARM uninit, local) Rate limiter applied {delay:.1f}s delay before subquery {subquery_index}" )

        # Make the API call
        response = await self._call_api(
            model             = self.config.subagent_model,
            system_prompt     = system_prompt,
            user_message      = user_message,
            call_type         = call_type,
            subquery_index    = subquery_index,
            use_web_search    = use_web_search,
            use_extended_thinking = False,  # Subagents don't use extended thinking
            max_tokens        = max_tokens,
            temperature       = temperature,
        )

        # Record actual token usage for rate limiter (input tokens include search results).
        # Phase 3: route through ApiResourceManager to match the acquire() path.
        # Fall back to local limiter if ARM is not initialised.
        if use_web_search:
            try:
                from cosa.utils.api_resource_manager import get_arm
                get_arm().record_call(
                    provider = "anthropic_web_search",
                    tokens   = response.input_tokens,
                )
            except RuntimeError:
                self._rate_limiter.record_usage(
                    tokens    = response.input_tokens,
                    call_type = "web_search"
                )

        return response

    async def call_with_json_output(
        self,
        system_prompt: str,
        user_message: str,
        model: Optional[ str ] = None,
        call_type: str = "structured",
        max_tokens: int = 4096
    ) -> dict:
        """
        Call API expecting JSON output.

        Ensures:
            - Parses response as JSON
            - Raises ValueError if response is not valid JSON

        Args:
            system_prompt: System prompt (should request JSON output)
            user_message: User message
            model: Model to use (defaults to lead model)
            call_type: Type of call for cost tracking
            max_tokens: Maximum tokens

        Returns:
            dict: Parsed JSON response
        """
        response = await self._call_api(
            model         = model or self.config.lead_model,
            system_prompt = system_prompt,
            user_message  = user_message,
            call_type     = call_type,
            max_tokens    = max_tokens,
        )

        # Try to parse JSON from response
        content = response.content.strip()

        # Handle markdown code blocks
        if content.startswith( "```json" ):
            content = content[ 7: ]
        if content.startswith( "```" ):
            content = content[ 3: ]
        if content.endswith( "```" ):
            content = content[ :-3 ]

        try:
            return json.loads( content.strip() )
        except json.JSONDecodeError as e:
            logger.error( f"Failed to parse JSON response: {e}" )
            logger.debug( f"Raw content: {response.content}" )
            raise ValueError( f"Response was not valid JSON: {e}" )

    async def _call_api(
        self,
        model: str,
        system_prompt: str,
        user_message: str,
        call_type: str = "unknown",
        subquery_index: Optional[ int ] = None,
        use_web_search: bool = False,
        use_extended_thinking: bool = False,
        max_tokens: int = 4096,
        temperature: float = 1.0
    ) -> APIResponse:
        """
        Internal method to call the Anthropic API.

        Handles:
        - Tool configuration (web search)
        - Extended thinking setup
        - Cost tracking
        - Error handling with retries

        Args:
            model: Model to use
            system_prompt: System prompt
            user_message: User message
            call_type: Type of call for cost tracking
            subquery_index: Subquery index for parallel tracking
            use_web_search: Enable web search tool
            use_extended_thinking: Enable extended thinking
            max_tokens: Maximum tokens
            temperature: Sampling temperature

        Returns:
            APIResponse: Structured response
        """
        # Build request parameters
        messages = [
            { "role": "user", "content": user_message }
        ]

        kwargs = {
            "model"      : model,
            "max_tokens" : max_tokens,
            "messages"   : messages,
        }

        # Add system prompt
        if system_prompt:
            kwargs[ "system" ] = system_prompt

        # Add temperature (not used with extended thinking)
        if not use_extended_thinking:
            kwargs[ "temperature" ] = temperature

        # Add web search tool
        if use_web_search:
            kwargs[ "tools" ] = [ WEB_SEARCH_TOOL ]

        # Add extended thinking
        if use_extended_thinking:
            kwargs[ "thinking" ] = {
                "type"         : "enabled",
                "budget_tokens": self.config.extended_thinking_budget,
            }

        if self.debug:
            print( f"[ResearchAPIClient] Calling {model} for {call_type}" )
            if use_web_search:
                print( f"[ResearchAPIClient] Web search enabled" )
            if use_extended_thinking:
                print( f"[ResearchAPIClient] Extended thinking enabled (budget: {self.config.extended_thinking_budget})" )

        # Make the API call with retry (longer delays for web search due to rate limits)
        response = await self._call_with_retry( kwargs, use_web_search=use_web_search )

        # Extract content and usage
        content = ""
        tool_use = []
        search_results = []

        for block in response.content:
            if hasattr( block, "text" ):
                content += block.text
            elif hasattr( block, "type" ) and block.type == "tool_use":
                tool_use.append( block )
            elif hasattr( block, "type" ) and block.type == "web_search_tool_result":
                # Extract search results
                if hasattr( block, "content" ):
                    search_results.extend( block.content )

        # Record usage
        if self.cost_tracker:
            try:
                self.cost_tracker.record_from_response(
                    model          = model,
                    response_usage = {
                        "input_tokens"                : response.usage.input_tokens,
                        "output_tokens"               : response.usage.output_tokens,
                        "cache_creation_input_tokens" : getattr( response.usage, "cache_creation_input_tokens", 0 ),
                        "cache_read_input_tokens"     : getattr( response.usage, "cache_read_input_tokens", 0 ),
                    },
                    call_type      = call_type,
                    subquery_index = subquery_index,
                )
            except BudgetExceededError:
                raise  # Let budget errors propagate

        if self.debug:
            print( f"[ResearchAPIClient] Response: {response.usage.input_tokens} in, {response.usage.output_tokens} out" )

        return APIResponse(
            content        = content,
            model          = model,
            input_tokens   = response.usage.input_tokens,
            output_tokens  = response.usage.output_tokens,
            stop_reason    = response.stop_reason,
            tool_use       = tool_use,
            search_results = search_results,
            raw_response   = response,
        )

    async def _call_with_retry(
        self,
        kwargs: dict,
        max_retries: int = 3,
        initial_delay: float = 1.0,
        use_web_search: bool = False
    ) -> Any:
        """
        Call API with exponential backoff retry.

        Handles:
        - Rate limiting (429)
        - Server errors (5xx)
        - Network timeouts

        For web search calls, uses longer delays due to Anthropic's strict
        rate limits (30,000 tokens/minute, but each search returns ~80,000+ tokens).

        Args:
            kwargs: API call parameters
            max_retries: Maximum retry attempts
            initial_delay: Initial delay in seconds
            use_web_search: If True, use longer delays for rate-limited web searches

        Returns:
            API response object
        """
        # Web search calls need much longer delays due to rate limits
        # Each search can return 80,000+ tokens but limit is 30,000/minute
        # With 8 retries and capped backoff:
        #   30s + 60s + 120s + 240s + 300s×4 = ~25 min max total wait
        # Most rate limits clear within 60-120s, so usually resolves by retry 2-3
        max_delay = 300.0  # Default cap for non-web-search

        if use_web_search:
            max_retries = 8
            initial_delay = 30.0   # Start with 30s wait for web search rate limits
            max_delay = 300.0      # Cap at 5 minutes per retry

        last_error = None
        delay = initial_delay

        for attempt in range( max_retries + 1 ):
            try:
                return await self._client.messages.create( **kwargs )

            except anthropic.RateLimitError as e:
                last_error = e
                if attempt < max_retries:
                    logger.warning( f"Rate limited, retrying in {delay:.0f}s (attempt {attempt + 1}/{max_retries})" )
                    await asyncio.sleep( delay )
                    delay = min( delay * 2, max_delay )  # Exponential backoff with cap

            except anthropic.APIStatusError as e:
                if e.status_code >= 500:
                    last_error = e
                    if attempt < max_retries:
                        logger.warning( f"Server error {e.status_code}, retrying in {delay:.0f}s" )
                        await asyncio.sleep( delay )
                        delay = min( delay * 2, max_delay )
                else:
                    raise  # Client errors (4xx) should not be retried

            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    logger.warning( f"API call failed: {e}, retrying in {delay:.0f}s" )
                    await asyncio.sleep( delay )
                    delay = min( delay * 2, max_delay )

        raise last_error

    async def close( self ):
        """Close the API client and release resources."""
        if hasattr( self._client, "close" ):
            await self._client.close()


def quick_smoke_test():
    """Quick smoke test for ResearchAPIClient."""
    import cosa.utils.util as cu

    cu.print_banner( "ResearchAPIClient Smoke Test", prepend_nl=True )

    try:
        # Test 1: Check import
        print( "Testing anthropic import..." )
        if not ANTHROPIC_AVAILABLE:
            print( "⚠ anthropic SDK not installed - skipping API tests" )
            print( "  Install with: pip install anthropic" )
            return
        print( "✓ anthropic SDK available" )

        # Test 2: Check API key presence (using firewalled pattern)
        print( "Testing API key detection (firewalled pattern)..." )
        print( f"  Checking env var: {ENV_VAR_NAME}" )
        print( f"  Checking local file: src/conf/keys/{KEY_FILE_NAME}" )

        # Try environment variable first
        api_key = os.environ.get( ENV_VAR_NAME )
        key_source = "environment"

        if not api_key:
            # Try local file
            try:
                import cosa.utils.util as cu
                api_key = cu.get_api_key( KEY_FILE_NAME )
                key_source = "local file"
            except Exception:
                pass

        if not api_key:
            print( f"⚠ API key not found - skipping live API tests" )
            print( f"  For testing/production: export {ENV_VAR_NAME}=your-key" )
            print( f"  For development: create src/conf/keys/{KEY_FILE_NAME}" )

            # Test instantiation without key should fail with clear message
            try:
                # Temporarily ensure env var is not set for this test
                old_env = os.environ.pop( ENV_VAR_NAME, None )
                client = ResearchAPIClient( debug=True )
                print( "✗ Should have raised ValueError for missing API key" )
                if old_env:
                    os.environ[ ENV_VAR_NAME ] = old_env
            except ValueError as e:
                print( f"✓ Correctly raised ValueError with instructions" )
                if old_env:
                    os.environ[ ENV_VAR_NAME ] = old_env

            return

        print( f"✓ API key found via {key_source} (starts with: {api_key[:10]}...)" )

        # Test 3: Instantiation with key
        print( "Testing instantiation..." )
        cost_tracker = CostTracker( session_id="smoke-test", debug=True )
        client = ResearchAPIClient(
            cost_tracker = cost_tracker,
            debug        = True
        )
        assert client.config.lead_model is not None
        assert client.config.subagent_model is not None
        print( f"✓ Client instantiated (lead={client.config.lead_model})" )

        # Test 4: APIResponse dataclass
        print( "Testing APIResponse dataclass..." )
        response = APIResponse(
            content      = "Test content",
            model        = "claude-sonnet-4-5",
            input_tokens = 100,
            output_tokens= 50,
            stop_reason  = "end_turn",
        )
        assert response.content == "Test content"
        assert response.input_tokens == 100
        print( "✓ APIResponse dataclass works" )

        # Test 5: WEB_SEARCH_TOOL definition
        print( "Testing WEB_SEARCH_TOOL definition..." )
        assert WEB_SEARCH_TOOL[ "type" ] == "web_search_20250305"
        assert WEB_SEARCH_TOOL[ "name" ] == "web_search"
        print( "✓ WEB_SEARCH_TOOL defined correctly" )

        # Test 6: Live API call (if key is valid)
        print( "\nTesting live API call..." )
        print( "  (This will use API credits)" )

        async def test_live_call():
            response = await client.call_lead_agent(
                system_prompt = "You are a helpful assistant. Respond briefly.",
                user_message  = "Say 'Hello, smoke test!' and nothing else.",
                call_type     = "smoke_test",
                max_tokens    = 50,
            )
            return response

        import asyncio
        response = asyncio.run( test_live_call() )
        print( f"✓ Live API call succeeded" )
        print( f"  Response: {response.content[:100]}" )
        print( f"  Tokens: {response.input_tokens} in, {response.output_tokens} out" )

        # Show cost summary
        print( "\nCost Summary:" )
        print( cost_tracker.get_cost_report() )

        print( "\n✓ ResearchAPIClient smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
