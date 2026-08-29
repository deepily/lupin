#!/usr/bin/env python3
"""
Claude script-generation client for the COSA Podcast Generator Agent.

BOUNDED-CC MIGRATION (Phase 1 — 2026-06-18)
===========================================
This client was migrated from the direct firewalled Anthropic SDK
(`AsyncAnthropic.messages.create`) to the **in-process Claude Agent SDK**
(`claude_agent_sdk.query`), matching the shipped BFE/TFE bounded-CC pattern
(ratified D-DR1 Option X). The four script-phase LLM methods now run on the
Max-subscription OAuth path.

This is a COST-SHIFT, NOT "free": the SDK still reports `total_cost_usd`
telemetry per call, but that spend is covered by the fixed Max plan — the
firewalled Anthropic console balance does not move. See:
  - Scope:        src/rnd/v0.1.8/2026.06.18-podcast-phase1-bounded-cc-scope.md
  - Ratification: src/rnd/v0.1.8/2026.06.18-bounded-cc-d1d9-ratification-package.md
  - Cost model:   src/docs/cost-model-bounded-cc-vs-firewalled-sdk.md

Podcast script generation is PURE TEXT SYNTHESIS, so the bounded-CC shape is
the simplest of the migration candidates: tools=[], no web search, no
can_use_tool callback, no progress-event translation. The audio (TTS) phase
is untouched and still uses ElevenLabs.

NOTE: `ClaudeAgentOptions` exposes no per-call `temperature`, so the historical
per-method creativity steer (e.g. 0.8 for script, 0.5 for JSON) is folded into
the system prompt instead (see `_temperature_to_steer`).
"""

import logging
from typing import Optional, Any
from dataclasses import dataclass

from .config import PodcastConfig
# D6-LENIENT JSON recovery — single source of truth lives in the parsing module
from .prompts.script_generation import lenient_json_loads

# Claude Agent SDK — graceful fallback (mirrors the BFE/TFE import guard)
try:
    from claude_agent_sdk import (
        ClaudeAgentOptions,
        AssistantMessage,
        TextBlock,
        ResultMessage,
        query as sdk_query,
    )
    SDK_AVAILABLE = True
except ImportError:  # pragma: no cover - claude-agent-sdk is installed in the canonical test/prod venv; this optional-dependency fallback is unreachable here
    SDK_AVAILABLE = False

logger = logging.getLogger( __name__ )


# =============================================================================
# Bounded-CC invocation constants (pure text synthesis)
# =============================================================================
# Script generation needs NO tools — it is pure dialogue synthesis. An empty
# allow-list disables every built-in tool, so the model can only emit text.
PODCAST_SCRIPT_TOOLS = []

# With tools=[] there is nothing to permit, so the permission mode never gates
# a real tool — the read-only guarantee comes from the empty allow-list above.
#
# It was previously "plan" as belt-and-suspenders. That reasoning was wrong:
# "plan" does not merely restrict tools, it puts the model in PLAN MODE, which
# changes what it produces. Asked for a podcast script, a model in plan mode
# writes a PLAN for a podcast script — 8,050 characters of prose that the JSON
# parser then correctly rejects with "no recoverable JSON object". Observed on
# job pg-efc6b2c8 (2026-08-04), where the response opened by apologising that it
# could not create `/home/rruiz/.claude/plans/create-a-podcast-script-*.md`.
#
# Valid values, read from the installed SDK (claude_agent_sdk/types.py:24,
# v0.1.56): "default" | "acceptEdits" | "plan" | "bypassPermissions" | "dontAsk".
PODCAST_PERMISSION_MODE = "default"


def _temperature_to_steer( temperature: float ) -> str:
    """
    Map a legacy per-call temperature into a system-prompt creativity steer.

    `ClaudeAgentOptions` exposes no per-call temperature, so the historical
    creativity intent — higher temperature meant more creative dialogue, lower
    meant more focused/precise output — is expressed in the prompt instead.

    Requires:
        - temperature is a float

    Ensures:
        - returns a non-empty steer string for high (>= 0.75) or low (<= 0.55)
          temperatures
        - returns "" for mid-range temperatures (no explicit steer)
    """
    if temperature >= 0.75:
        return "Write with creative, natural, varied phrasing."
    if temperature <= 0.55:
        return "Write with precise, focused, deterministic phrasing."
    return ""


@dataclass
class APIResponse:
    """
    Structured response from a script-phase LLM call.

    Contains the response text, token usage, stop reason, and the SDK-reported
    cost telemetry (covered by the Max plan — see module docstring).
    """
    content       : str
    model         : str
    input_tokens  : int
    output_tokens : int
    stop_reason   : str
    sdk_cost_usd  : float = 0.0
    raw_response  : Any   = None


@dataclass
class CostEstimate:
    """
    Cost tracking for script-phase LLM calls.

    Tracks token usage with a token-based price estimate (`estimated_cost_usd`,
    used by the orchestrator's metadata) AND the SDK-reported telemetry
    (`total_sdk_cost_usd`). Under the bounded-CC path the SDK telemetry is
    covered by the fixed Max plan and is NOT billed per token.
    """
    total_input_tokens  : int   = 0
    total_output_tokens : int   = 0
    total_api_calls     : int   = 0
    estimated_cost_usd  : float = 0.0
    total_sdk_cost_usd  : float = 0.0

    # Pricing per million tokens (approximate, as of 2025)
    OPUS_INPUT_PRICE    : float = 15.0
    OPUS_OUTPUT_PRICE   : float = 75.0
    SONNET_INPUT_PRICE  : float = 3.0
    SONNET_OUTPUT_PRICE : float = 15.0

    def add_usage( self, model: str, input_tokens: int, output_tokens: int ):
        """
        Add token usage from an LLM call (token-based price estimate).

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

    def add_sdk_cost( self, cost_usd: float ):
        """
        Accumulate the SDK-reported per-call cost telemetry.

        Args:
            cost_usd: `ResultMessage.total_cost_usd` for one call (telemetry only —
                      covered by the Max plan, not billed per token)
        """
        self.total_sdk_cost_usd += cost_usd

    def get_summary( self ) -> str:
        """Get human-readable cost summary (with the Max-plan disclaimer)."""
        return (
            f"API Calls: {self.total_api_calls} | "
            f"Tokens: {self.total_input_tokens:,} in, {self.total_output_tokens:,} out | "
            f"Est. Cost: ${self.estimated_cost_usd:.4f} | "
            f"SDK telemetry: ${self.total_sdk_cost_usd:.4f} (covered by Max plan — not billed per-token)"
        )


class PodcastAPIClient:
    """
    Bounded-CC script-generation client (in-process Claude Agent SDK).

    Requires:
        - claude_agent_sdk is installed (SDK_AVAILABLE == True)

    Ensures:
        - Async, non-blocking script-phase LLM calls via `sdk_query`
        - Max-plan OAuth billing (no API key — see module docstring)
        - Integrated token + SDK-cost tracking
        - JSON output support for structured responses

    No API key is required: `sdk_query` authenticates via the Claude Code /
    Claude Agent SDK Max-subscription OAuth path. The former firewalled-key
    machinery was removed in the bounded-CC migration.
    """

    def __init__(
        self,
        config: Optional[ PodcastConfig ] = None,
        debug: bool = False,
        verbose: bool = False
    ):
        """
        Initialize the script-generation client.

        Requires:
            - claude_agent_sdk is installed

        Ensures:
            - Raises ImportError if the SDK is unavailable
            - cost tracking is initialized

        Args:
            config: Podcast configuration (uses defaults if None)
            debug: Enable debug output
            verbose: Enable verbose output

        Raises:
            ImportError: if claude_agent_sdk is not installed
        """
        if not SDK_AVAILABLE:
            raise ImportError(
                "claude_agent_sdk not installed. "
                "Install with: pip install claude-agent-sdk"
            )

        self.config  = config or PodcastConfig()
        self.debug   = debug
        self.verbose = verbose

        # Cost tracking
        self.cost_estimate = CostEstimate()

        if self.debug:
            print( f"[PodcastAPIClient] Bounded-CC mode (in-process sdk_query, Max-plan OAuth)" )
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
            max_tokens: Retained for signature parity (unused on the bounded path)
            temperature: Folded into the system-prompt creativity steer

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

        Uses a higher creativity steer for more natural dialogue.

        Args:
            system_prompt: System prompt with personality instructions
            user_message: Script generation request
            max_tokens: Retained for signature parity (unused on the bounded path)
            temperature: Folded into the system-prompt creativity steer

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

        Args:
            system_prompt: System prompt for revision
            user_message: Revision request with feedback
            max_tokens: Retained for signature parity (unused on the bounded path)
            temperature: Folded into the system-prompt creativity steer

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
        Call the model expecting JSON output (D6-LENIENT extraction).

        Ensures:
            - Strips markdown code fences
            - Recovers a JSON object embedded in surrounding prose (bounded CC
              completions can be chattier than `messages.create`)
            - Raises ValueError only if no JSON object can be recovered

        Args:
            system_prompt: System prompt (should request JSON output)
            user_message: User message
            max_tokens: Retained for signature parity (unused on the bounded path)

        Returns:
            dict: Parsed JSON response

        Raises:
            ValueError: if no valid JSON object can be recovered
        """
        response = await self._call_api(
            model         = self.config.script_model,
            system_prompt = system_prompt,
            user_message  = user_message,
            max_tokens    = max_tokens,
            temperature   = 0.5,  # low → "precise" steer for structured output
            call_type     = "json_output",
        )

        parsed = lenient_json_loads( response.content )
        if parsed is None:
            logger.error( "Failed to recover JSON object from response" )
            logger.debug( f"Raw content: {response.content}" )
            raise ValueError( "Response did not contain a recoverable JSON object" )
        return parsed

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
        Internal bounded-CC call via in-process `sdk_query`.

        Requires:
            - SDK_AVAILABLE is True

        Ensures:
            - Builds tools=[] / read-only options (pure synthesis)
            - Folds temperature into the system-prompt creativity steer
            - Concatenates all assistant TextBlocks into the response content
            - Records token usage + SDK cost telemetry

        Args:
            model: Model to use
            system_prompt: System prompt
            user_message: User message
            call_type: Type of call for logging
            max_tokens: Retained for signature parity (unused on the bounded path)
            temperature: Folded into the creativity steer

        Returns:
            APIResponse: Structured response
        """
        steer            = _temperature_to_steer( temperature )
        effective_system = system_prompt or ""
        if steer:
            effective_system = ( effective_system + "\n\n" + steer ).strip()

        options = ClaudeAgentOptions(
            model           = model,
            system_prompt   = effective_system or None,
            tools           = PODCAST_SCRIPT_TOOLS,
            permission_mode = PODCAST_PERMISSION_MODE,
            max_turns       = self.config.script_max_turns,
        )

        if self.debug:
            print( f"[PodcastAPIClient] sdk_query {model} for {call_type} (max_turns={self.config.script_max_turns})" )

        collected      = []
        input_tokens   = 0
        output_tokens  = 0
        sdk_cost_usd   = 0.0
        stop_reason    = "end_turn"

        async for message in sdk_query( prompt=user_message, options=options ):
            if isinstance( message, AssistantMessage ):
                for block in message.content:
                    if isinstance( block, TextBlock ):
                        collected.append( block.text )
            elif isinstance( message, TextBlock ):
                collected.append( message.text )
            elif isinstance( message, ResultMessage ):
                usage         = message.usage or {}
                input_tokens  = usage.get( "input_tokens", 0 )
                output_tokens = usage.get( "output_tokens", 0 )
                sdk_cost_usd  = message.total_cost_usd or 0.0
                stop_reason   = message.stop_reason or "end_turn"

        content = "".join( collected ).strip()

        # Record usage (token estimate) + SDK cost telemetry (Max-plan covered)
        self.cost_estimate.add_usage(
            model         = model,
            input_tokens  = input_tokens,
            output_tokens = output_tokens,
        )
        self.cost_estimate.add_sdk_cost( sdk_cost_usd )

        if self.debug:
            print( f"[PodcastAPIClient] Response: {input_tokens} in, {output_tokens} out, sdk_cost_usd=${sdk_cost_usd:.4f}" )

        return APIResponse(
            content       = content,
            model         = model,
            input_tokens  = input_tokens,
            output_tokens = output_tokens,
            stop_reason   = stop_reason,
            sdk_cost_usd  = sdk_cost_usd,
            raw_response  = None,
        )

    def get_cost_summary( self ) -> str:
        """Get human-readable cost summary."""
        return self.cost_estimate.get_summary()

    async def close( self ):
        """
        Release client resources.

        No-op under the bounded-CC path: `sdk_query` is stateless (no persistent
        client/connection to close). Retained for API compatibility.
        """
        return None


def quick_smoke_test():
    """Quick smoke test for PodcastAPIClient (bounded-CC path)."""
    import cosa.utils.util as cu

    cu.print_banner( "PodcastAPIClient Smoke Test (bounded-CC)", prepend_nl=True )

    try:
        # Test 1: SDK availability
        print( "Testing claude_agent_sdk import..." )
        if not SDK_AVAILABLE:
            print( "⚠ claude_agent_sdk not installed - skipping bounded-CC tests" )
            print( "  Install with: pip install claude-agent-sdk" )
            return
        print( "✓ claude_agent_sdk available" )

        # Test 2: Instantiation (no API key needed — OAuth path)
        print( "Testing instantiation..." )
        client = PodcastAPIClient( debug=True )
        assert client.config.script_model is not None
        print( f"✓ Client instantiated (model={client.config.script_model})" )

        # Test 3: APIResponse dataclass
        print( "Testing APIResponse dataclass..." )
        response = APIResponse(
            content       = "Test content",
            model         = "claude-opus-4-6",
            input_tokens  = 100,
            output_tokens = 50,
            stop_reason   = "end_turn",
        )
        assert response.content == "Test content"
        assert response.sdk_cost_usd == 0.0
        print( "✓ APIResponse dataclass works" )

        # Test 4: CostEstimate tracking (+ SDK telemetry)
        print( "Testing CostEstimate..." )
        cost = CostEstimate()
        cost.add_usage( "claude-opus-4-6", 1000, 500 )
        cost.add_usage( "claude-sonnet-4-6", 2000, 1000 )
        cost.add_sdk_cost( 0.2051 )
        assert cost.total_api_calls == 2
        assert cost.total_input_tokens == 3000
        summary = cost.get_summary()
        assert "API Calls: 2" in summary
        assert "Max plan" in summary
        print( f"✓ CostEstimate: {summary}" )

        # Test 5: temperature → steer mapping
        print( "Testing temperature steer mapping..." )
        assert _temperature_to_steer( 0.8 ) != ""
        assert _temperature_to_steer( 0.5 ) != ""
        assert _temperature_to_steer( 0.7 ) == ""
        print( "✓ Temperature steer mapping works" )

        # Test 6: lenient JSON recovery (canonical helper in script_generation)
        print( "Testing lenient JSON recovery..." )
        assert lenient_json_loads( '```json\n{"a": 1}\n```' ) == { "a": 1 }
        assert lenient_json_loads( 'Here you go: {"b": 2} cheers!' ) == { "b": 2 }
        assert lenient_json_loads( "no json here" ) is None
        print( "✓ Lenient JSON recovery works" )

        # Test 7: Live bounded-CC call
        print( "\nTesting live bounded-CC call (Max-plan OAuth — covered cost)..." )

        async def test_live_call():
            return await client.call_for_analysis(
                system_prompt = "You are a helpful assistant. Respond briefly.",
                user_message  = "Say 'Hello, podcast test!' and nothing else.",
                max_tokens    = 50,
            )

        import asyncio
        response = asyncio.run( test_live_call() )
        print( f"✓ Live bounded-CC call succeeded" )
        print( f"  Response: {response.content[ :100 ]}" )
        print( f"  {client.get_cost_summary()}" )

        print( "\n✓ PodcastAPIClient smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
