#!/usr/bin/env python3
"""
Claude API Client for COSA Podcast Generator Agent.

Provides async wrapper for Claude API with:
- Model selection (Opus for script generation)
- Structured JSON output support
- Per-request cost tracking
- Graceful error handling with retries

Follows the firewalled API key pattern from Deep Research Agent.
"""

import os
import json
import asyncio
import logging
from typing import Optional, Any
from dataclasses import dataclass, field

try:
    import anthropic
    from anthropic import AsyncAnthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    AsyncAnthropic = None

from .config import PodcastConfig

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

ENV_VAR_NAME  = "ANTHROPIC_API_KEY_FIREWALLED"
KEY_FILE_NAME = "anthropic-api-key-firewalled"


@dataclass
class APIResponse:
    """
    Structured response from an API call.

    Contains the response content, usage data, and model information.
    """
    content       : str
    model         : str
    input_tokens  : int
    output_tokens : int
    stop_reason   : str
    raw_response  : Any = None


@dataclass
class CostEstimate:
    """
    Simple cost tracking for API calls.

    Tracks token usage and estimates cost based on model pricing.
    """
    total_input_tokens  : int   = 0
    total_output_tokens : int   = 0
    total_api_calls     : int   = 0
    estimated_cost_usd  : float = 0.0

    # Pricing per million tokens (approximate, as of 2025)
    OPUS_INPUT_PRICE    : float = 15.0
    OPUS_OUTPUT_PRICE   : float = 75.0
    SONNET_INPUT_PRICE  : float = 3.0
    SONNET_OUTPUT_PRICE : float = 15.0

    def add_usage( self, model: str, input_tokens: int, output_tokens: int ):
        """
        Add usage from an API call.

        Args:
            model: Model name used
            input_tokens: Input tokens consumed
            output_tokens: Output tokens generated
        """
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_api_calls += 1

        # Estimate cost based on model
        if "opus" in model.lower():
            cost = ( input_tokens * self.OPUS_INPUT_PRICE / 1_000_000 +
                     output_tokens * self.OPUS_OUTPUT_PRICE / 1_000_000 )
        else:  # Sonnet or other
            cost = ( input_tokens * self.SONNET_INPUT_PRICE / 1_000_000 +
                     output_tokens * self.SONNET_OUTPUT_PRICE / 1_000_000 )

        self.estimated_cost_usd += cost

    def get_summary( self ) -> str:
        """Get human-readable cost summary."""
        return (
            f"API Calls: {self.total_api_calls} | "
            f"Tokens: {self.total_input_tokens:,} in, {self.total_output_tokens:,} out | "
            f"Est. Cost: ${self.estimated_cost_usd:.4f}"
        )


class PodcastAPIClient:
    """
    Async Anthropic API client for podcast script generation.

    Requires:
        - anthropic SDK is installed
        - One of the following API key sources:
          1. api_key parameter (explicit)
          2. ANTHROPIC_API_KEY_FIREWALLED environment variable
          3. src/conf/keys/anthropic-api-key-firewalled file

    Ensures:
        - Async execution for non-blocking calls
        - Integrated cost tracking
        - JSON output support for structured responses
    """

    def __init__(
        self,
        config: Optional[ PodcastConfig ] = None,
        api_key: Optional[ str ] = None,
        debug: bool = False,
        verbose: bool = False
    ):
        """
        Initialize the API client.

        Args:
            config: Podcast configuration (uses defaults if None)
            api_key: Anthropic API key (uses env var/file if None)
            debug: Enable debug output
            verbose: Enable verbose output
        """
        if not ANTHROPIC_AVAILABLE:
            raise ImportError(
                "anthropic SDK not installed. "
                "Install with: pip install anthropic"
            )

        self.config  = config or PodcastConfig()
        self.debug   = debug
        self.verbose = verbose

        # Get API key using firewalled pattern
        self.api_key    = api_key
        self.key_source = "parameter"

        if not self.api_key:
            self.api_key = os.environ.get( ENV_VAR_NAME )
            self.key_source = "environment"

        if not self.api_key:
            try:
                import cosa.utils.util as cu
                self.api_key = cu.get_api_key( KEY_FILE_NAME )
                self.key_source = "local file"
            except Exception as e:
                if self.debug:
                    print( f"[PodcastAPIClient] Could not load local key file: {e}" )

        if not self.api_key:
            raise ValueError(
                f"Anthropic API key not found. Either:\n"
                f"  1. Pass api_key parameter\n"
                f"  2. Set {ENV_VAR_NAME} environment variable\n"
                f"  3. Create src/conf/keys/{KEY_FILE_NAME} file"
            )

        # Initialize async client
        self._client = AsyncAnthropic( api_key=self.api_key )

        # Initialize cost tracking
        self.cost_estimate = CostEstimate()

        if self.debug:
            print( f"[PodcastAPIClient] API key source: {self.key_source}" )
            print( f"[PodcastAPIClient] Script model: {self.config.script_model}" )

    async def call_for_analysis(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 4096,
        temperature: float = 0.7
    ) -> APIResponse:
        """
        Call Claude for content analysis.

        Args:
            system_prompt: System prompt for analysis
            user_message: Content to analyze
            max_tokens: Maximum response tokens
            temperature: Sampling temperature

        Returns:
            APIResponse: Structured response with analysis
        """
        return await self._call_api(
            model         = self.config.script_model,
            system_prompt = system_prompt,
            user_message  = user_message,
            max_tokens    = max_tokens,
            temperature   = temperature,
            call_type     = "analysis",
        )

    async def call_for_script(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 8192,
        temperature: float = 0.8
    ) -> APIResponse:
        """
        Call Claude for script generation.

        Uses slightly higher temperature for more creative dialogue.

        Args:
            system_prompt: System prompt with personality instructions
            user_message: Script generation request
            max_tokens: Maximum response tokens (scripts can be long)
            temperature: Sampling temperature (higher for creativity)

        Returns:
            APIResponse: Structured response with script
        """
        return await self._call_api(
            model         = self.config.script_model,
            system_prompt = system_prompt,
            user_message  = user_message,
            max_tokens    = max_tokens,
            temperature   = temperature,
            call_type     = "script_generation",
        )

    async def call_for_revision(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 8192,
        temperature: float = 0.6
    ) -> APIResponse:
        """
        Call Claude for script revision.

        Uses lower temperature for more focused revisions.

        Args:
            system_prompt: System prompt for revision
            user_message: Revision request with feedback
            max_tokens: Maximum response tokens
            temperature: Sampling temperature (lower for precision)

        Returns:
            APIResponse: Structured response with revised script
        """
        return await self._call_api(
            model         = self.config.script_model,
            system_prompt = system_prompt,
            user_message  = user_message,
            max_tokens    = max_tokens,
            temperature   = temperature,
            call_type     = "revision",
        )

    async def call_with_json_output(
        self,
        system_prompt: str,
        user_message: str,
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
            max_tokens: Maximum tokens

        Returns:
            dict: Parsed JSON response
        """
        response = await self._call_api(
            model         = self.config.script_model,
            system_prompt = system_prompt,
            user_message  = user_message,
            max_tokens    = max_tokens,
            temperature   = 0.5,  # Lower temp for structured output
            call_type     = "json_output",
        )

        # Parse JSON from response
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
        max_tokens: int = 4096,
        temperature: float = 0.7
    ) -> APIResponse:
        """
        Internal method to call the Anthropic API.

        Args:
            model: Model to use
            system_prompt: System prompt
            user_message: User message
            call_type: Type of call for logging
            max_tokens: Maximum tokens
            temperature: Sampling temperature

        Returns:
            APIResponse: Structured response
        """
        messages = [
            { "role": "user", "content": user_message }
        ]

        kwargs = {
            "model"       : model,
            "max_tokens"  : max_tokens,
            "messages"    : messages,
            "temperature" : temperature,
        }

        if system_prompt:
            kwargs[ "system" ] = system_prompt

        if self.debug:
            print( f"[PodcastAPIClient] Calling {model} for {call_type}" )

        # Make API call with retry
        response = await self._call_with_retry( kwargs )

        # Extract content
        content = ""
        for block in response.content:
            if hasattr( block, "text" ):
                content += block.text

        # Record usage
        self.cost_estimate.add_usage(
            model         = model,
            input_tokens  = response.usage.input_tokens,
            output_tokens = response.usage.output_tokens,
        )

        if self.debug:
            print( f"[PodcastAPIClient] Response: {response.usage.input_tokens} in, {response.usage.output_tokens} out" )

        return APIResponse(
            content       = content,
            model         = model,
            input_tokens  = response.usage.input_tokens,
            output_tokens = response.usage.output_tokens,
            stop_reason   = response.stop_reason,
            raw_response  = response,
        )

    async def _call_with_retry(
        self,
        kwargs: dict,
        max_retries: int = 3,
        initial_delay: float = 1.0
    ) -> Any:
        """
        Call API with exponential backoff retry.

        Args:
            kwargs: API call parameters
            max_retries: Maximum retry attempts
            initial_delay: Initial delay in seconds

        Returns:
            API response object
        """
        last_error = None
        delay = initial_delay

        for attempt in range( max_retries + 1 ):
            try:
                return await self._client.messages.create( **kwargs )

            except anthropic.RateLimitError as e:
                last_error = e
                if attempt < max_retries:
                    logger.warning( f"Rate limited, retrying in {delay:.0f}s (attempt {attempt + 1})" )
                    await asyncio.sleep( delay )
                    delay *= 2

            except anthropic.APIStatusError as e:
                if e.status_code >= 500:
                    last_error = e
                    if attempt < max_retries:
                        logger.warning( f"Server error {e.status_code}, retrying in {delay:.0f}s" )
                        await asyncio.sleep( delay )
                        delay *= 2
                else:
                    raise

            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    logger.warning( f"API call failed: {e}, retrying in {delay:.0f}s" )
                    await asyncio.sleep( delay )
                    delay *= 2

        raise last_error

    def get_cost_summary( self ) -> str:
        """Get human-readable cost summary."""
        return self.cost_estimate.get_summary()

    async def close( self ):
        """Close the API client and release resources."""
        if hasattr( self._client, "close" ):
            await self._client.close()


def quick_smoke_test():
    """Quick smoke test for PodcastAPIClient."""
    import cosa.utils.util as cu

    cu.print_banner( "PodcastAPIClient Smoke Test", prepend_nl=True )

    try:
        # Test 1: Check import
        print( "Testing anthropic import..." )
        if not ANTHROPIC_AVAILABLE:
            print( "⚠ anthropic SDK not installed - skipping API tests" )
            print( "  Install with: pip install anthropic" )
            return
        print( "✓ anthropic SDK available" )

        # Test 2: Check API key presence
        print( "Testing API key detection (firewalled pattern)..." )
        print( f"  Checking env var: {ENV_VAR_NAME}" )
        print( f"  Checking local file: src/conf/keys/{KEY_FILE_NAME}" )

        api_key = os.environ.get( ENV_VAR_NAME )
        key_source = "environment"

        if not api_key:
            try:
                api_key = cu.get_api_key( KEY_FILE_NAME )
                key_source = "local file"
            except Exception:
                pass

        if not api_key:
            print( f"⚠ API key not found - skipping live API tests" )
            print( f"  For testing: export {ENV_VAR_NAME}=your-key" )
            print( f"  For development: create src/conf/keys/{KEY_FILE_NAME}" )
            return

        print( f"✓ API key found via {key_source}" )

        # Test 3: Instantiation
        print( "Testing instantiation..." )
        client = PodcastAPIClient( debug=True )
        assert client.config.script_model is not None
        print( f"✓ Client instantiated (model={client.config.script_model})" )

        # Test 4: APIResponse dataclass
        print( "Testing APIResponse dataclass..." )
        response = APIResponse(
            content       = "Test content",
            model         = "claude-opus-4",
            input_tokens  = 100,
            output_tokens = 50,
            stop_reason   = "end_turn",
        )
        assert response.content == "Test content"
        print( "✓ APIResponse dataclass works" )

        # Test 5: CostEstimate tracking
        print( "Testing CostEstimate..." )
        cost = CostEstimate()
        cost.add_usage( "claude-opus-4", 1000, 500 )
        cost.add_usage( "claude-sonnet-4", 2000, 1000 )
        assert cost.total_api_calls == 2
        assert cost.total_input_tokens == 3000
        summary = cost.get_summary()
        assert "API Calls: 2" in summary
        print( f"✓ CostEstimate: {summary}" )

        # Test 6: Live API call
        print( "\nTesting live API call..." )
        print( "  (This will use API credits)" )

        async def test_live_call():
            response = await client.call_for_analysis(
                system_prompt = "You are a helpful assistant. Respond briefly.",
                user_message  = "Say 'Hello, podcast test!' and nothing else.",
                max_tokens    = 50,
            )
            return response

        import asyncio
        response = asyncio.run( test_live_call() )
        print( f"✓ Live API call succeeded" )
        print( f"  Response: {response.content[ :100 ]}" )
        print( f"  {client.get_cost_summary()}" )

        print( "\n✓ PodcastAPIClient smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
