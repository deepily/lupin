#!/usr/bin/env python3
"""
Claude content-generation client for the Presentation Generator Agent.

BOUNDED-CC MIGRATION (Phase 2 — 2026-06-18)
===========================================
This client was migrated from the direct firewalled Anthropic SDK
(`AsyncAnthropic.messages.create`) to the **in-process Claude Agent SDK**
(`claude_agent_sdk.query`), matching the shipped BFE/TFE/Podcast bounded-CC
pattern (ratified D-DR1 Option X). The seven content-phase LLM methods now run
on the Max-subscription OAuth path.

This is a COST-SHIFT, NOT "free": the SDK still reports `total_cost_usd`
telemetry per call, but that spend is covered by the fixed Max plan — the
firewalled Anthropic console balance does not move. See:
  - Scope:        src/rnd/v0.1.8/2026.06.18-presentation-phase2-bounded-cc-scope.md
  - Ratification: src/rnd/v0.1.8/2026.06.18-bounded-cc-d1d9-ratification-package.md
  - Cost model:   src/docs/cost-model-bounded-cc-vs-firewalled-sdk.md

Presentation content generation is PURE TEXT/CODE SYNTHESIS, so the bounded-CC
shape is: tools=[], no web search, no can_use_tool. The Gemini image/video path
(`gemini_client.py`, NanoBanana/Veo) is NON-Anthropic and UNTOUCHED. The pptx /
Marp assembly + diagram rendering phases are untouched.

NOTE: `ClaudeAgentOptions` exposes no per-call `temperature`, so the historical
per-method creativity steer is folded into the system prompt (see
`_temperature_to_steer`).

D6 = STRICT for Presentation: `call_with_json_output` (and the prompt-module
parsers) robustly recover the JSON object from chatty output but FAIL LOUD on
unrecoverable content — structured slide data is consumed downstream by pptx
rendering, so an empty/malformed result is a real defect, not cosmetic drift.
"""

import logging
from typing import Optional, Any
from dataclasses import dataclass

from .config import PresentationConfig
from .prompts.json_recovery import recover_json_object

# Claude Agent SDK — graceful fallback (mirrors the BFE/TFE/Podcast import guard)
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
# Bounded-CC invocation constants (pure text/code synthesis)
# =============================================================================
# Content/diagram generation needs NO tools. An empty allow-list disables every
# built-in tool, so the model can only emit text.
PRESENTATION_CONTENT_TOOLS = []

# "default", NOT "plan" — and the comment that used to sit here was wrong twice
# over. It claimed "plan" was harmless belt-and-suspenders, and cited the Podcast
# migration as having live-verified that. Podcast REFUTED it on 2026-08-04 and
# changed to "default" (5c45edf6): plan mode does not merely restrict tools, it
# changes what the model PRODUCES. Asked for a script it wrote a plan FOR a
# script, and the JSON parser correctly rejected the prose. The presentation twin
# was left behind and failed the same way that night — job pr-62254a7f, 23:08 EDT,
# "Outline generation returned no usable entries". tools=[] is what keeps this
# read-only; the mode never needed to.
PRESENTATION_PERMISSION_MODE = "default"


def _temperature_to_steer( temperature: float ) -> str:
    """
    Map a legacy per-call temperature into a system-prompt creativity steer.

    `ClaudeAgentOptions` exposes no per-call temperature, so the historical
    creativity intent — higher temperature meant more creative prose, lower
    meant more deterministic output (diagram code) — is expressed in the prompt.

    Requires:
        - temperature is a float

    Ensures:
        - returns a non-empty steer for high (>= 0.75) or low (<= 0.55)
          temperatures; "" for mid-range
    """
    if temperature >= 0.75:
        return "Write with creative, natural, varied phrasing."
    if temperature <= 0.55:
        return "Write with precise, focused, deterministic output."
    return ""


@dataclass
class APIResponse:
    """
    Structured response from a content-phase LLM call.

    Contains the response text, token usage, stop reason, and the SDK-reported
    cost telemetry (covered by the Max plan — see module docstring).
    """
    content       : str
    model         : str
    input_tokens  : int
    output_tokens : int
    stop_reason   : Optional[ str ]   # None = completion state UNKNOWN (not "end_turn")
    sdk_cost_usd  : float = 0.0
    raw_response  : Any   = None


@dataclass
class CostEstimate:
    """
    Cost tracking for content-phase LLM calls.

    Tracks token usage with a token-based price estimate (`estimated_cost_usd`)
    AND the SDK-reported telemetry (`total_sdk_cost_usd`). Under the bounded-CC
    path the SDK telemetry is covered by the fixed Max plan, NOT billed per token.
    """
    total_input_tokens  : int   = 0
    total_output_tokens : int   = 0
    total_api_calls     : int   = 0
    estimated_cost_usd  : float = 0.0
    total_sdk_cost_usd  : float = 0.0

    # Pricing per million tokens (as of 2026-04)
    OPUS_INPUT_PRICE    : float = 15.0
    OPUS_OUTPUT_PRICE   : float = 75.0
    SONNET_INPUT_PRICE  : float = 3.0
    SONNET_OUTPUT_PRICE : float = 15.0
    HAIKU_INPUT_PRICE   : float = 0.80
    HAIKU_OUTPUT_PRICE  : float = 4.0

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

        model_lower = model.lower()
        if "opus" in model_lower:
            cost = ( input_tokens * self.OPUS_INPUT_PRICE / 1_000_000 +
                     output_tokens * self.OPUS_OUTPUT_PRICE / 1_000_000 )
        elif "haiku" in model_lower:
            cost = ( input_tokens * self.HAIKU_INPUT_PRICE / 1_000_000 +
                     output_tokens * self.HAIKU_OUTPUT_PRICE / 1_000_000 )
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


class PresentationAPIClient:
    """
    Bounded-CC content-generation client (in-process Claude Agent SDK).

    Requires:
        - claude_agent_sdk is installed (SDK_AVAILABLE == True)

    Ensures:
        - Async, non-blocking content-phase LLM calls via `sdk_query`
        - Max-plan OAuth billing (no API key — see module docstring)
        - Integrated token + SDK-cost tracking
        - STRICT JSON output support for structured responses

    No API key is required: `sdk_query` authenticates via the Claude Code /
    Claude Agent SDK Max-subscription OAuth path. The former firewalled-key
    machinery was removed in the bounded-CC migration. The Gemini path is
    separate and unaffected.
    """

    def __init__(
        self,
        config: Optional[ PresentationConfig ] = None,
        debug: bool = False,
        verbose: bool = False
    ):
        """
        Initialize the content-generation client.

        Requires:
            - claude_agent_sdk is installed

        Ensures:
            - Raises ImportError if the SDK is unavailable
            - cost tracking is initialized

        Args:
            config: Presentation configuration (uses defaults if None)
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

        self.config  = config or PresentationConfig()
        self.debug   = debug
        self.verbose = verbose

        # Cost tracking
        self.cost_estimate = CostEstimate()

        if self.debug:
            print( f"[PresentationAPIClient] Bounded-CC mode (in-process sdk_query, Max-plan OAuth)" )
            print( f"[PresentationAPIClient] Content model: {self.config.content_model}" )

    # =========================================================================
    # Public API Methods
    # =========================================================================

    async def call_for_analysis(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 4096,
        temperature: float = 0.7
    ) -> APIResponse:
        """Call Claude for narrative analysis."""
        return await self._call_api(
            model=self.config.content_model, system_prompt=system_prompt,
            user_message=user_message, max_tokens=max_tokens,
            temperature=temperature, call_type="narrative_analysis",
        )

    async def call_for_outline(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 4096,
        temperature: float = 0.7
    ) -> APIResponse:
        """Call Claude for slide outline generation."""
        return await self._call_api(
            model=self.config.content_model, system_prompt=system_prompt,
            user_message=user_message, max_tokens=max_tokens,
            temperature=temperature, call_type="outline_generation",
        )

    async def call_for_elaboration(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 8192,
        temperature: float = 0.7
    ) -> APIResponse:
        """Call Claude for full slide content elaboration."""
        return await self._call_api(
            model=self.config.content_model, system_prompt=system_prompt,
            user_message=user_message, max_tokens=max_tokens,
            temperature=temperature, call_type="elaboration",
        )

    async def call_for_mermaid(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 2048,
        temperature: float = 0.3
    ) -> APIResponse:
        """Generate Mermaid diagram code (text output, not JSON)."""
        return await self._call_api(
            model=self.config.content_model, system_prompt=system_prompt,
            user_message=user_message, max_tokens=max_tokens,
            temperature=temperature, call_type="mermaid",
        )

    async def call_for_matplotlib(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 4096,
        temperature: float = 0.2
    ) -> APIResponse:
        """Generate Matplotlib Python code (text output, not JSON)."""
        return await self._call_api(
            model=self.config.content_model, system_prompt=system_prompt,
            user_message=user_message, max_tokens=max_tokens,
            temperature=temperature, call_type="matplotlib",
        )

    async def call_for_d2(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 2048,
        temperature: float = 0.3
    ) -> APIResponse:
        """Generate D2 diagram code (text output, not JSON)."""
        return await self._call_api(
            model=self.config.content_model, system_prompt=system_prompt,
            user_message=user_message, max_tokens=max_tokens,
            temperature=temperature, call_type="d2",
        )

    async def call_with_json_output(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 4096
    ) -> dict:
        """
        Call the model expecting JSON output (D6-STRICT).

        Ensures:
            - Robustly recovers a JSON object from chatty output (fence-strip +
              embedded-object extraction)
            - FAILS LOUD (raises ValueError) if no JSON object can be recovered —
              never substitutes a default (structured output is consumed downstream)

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
            model=self.config.content_model, system_prompt=system_prompt,
            user_message=user_message, max_tokens=max_tokens,
            temperature=0.5, call_type="json_output",
        )

        parsed = recover_json_object( response.content )
        if parsed is None:
            logger.error( "Failed to recover JSON object from response" )
            logger.debug( f"Raw content: {response.content}" )
            raise ValueError( "Response did not contain a recoverable JSON object" )
        return parsed

    # =========================================================================
    # Internal Methods
    # =========================================================================

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
            tools           = PRESENTATION_CONTENT_TOOLS,
            permission_mode = PRESENTATION_PERMISSION_MODE,
            max_turns       = self.config.content_max_turns,
        )

        if self.debug:
            print( f"[PresentationAPIClient] sdk_query {model} for {call_type} (max_turns={self.config.content_max_turns})" )

        collected     = []
        input_tokens  = 0
        output_tokens = 0
        sdk_cost_usd  = 0.0
        # UNKNOWN until a ResultMessage reports it. Do NOT seed "end_turn": that
        # coerces "no completion signal arrived" into "completed cleanly", and
        # orchestrator._elaborate_async (is_truncated = stop_reason != "end_turn")
        # would then skip the chunked fallback exactly when it is needed (bug
        # 98d937c2, fail-open). None reads as truncated downstream — the safe way.
        stop_reason   = None

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
                stop_reason   = message.stop_reason   # keep None as UNKNOWN — never coerce to "end_turn"

        content = "".join( collected ).strip()

        self.cost_estimate.add_usage(
            model=model, input_tokens=input_tokens, output_tokens=output_tokens,
        )
        self.cost_estimate.add_sdk_cost( sdk_cost_usd )

        if self.debug:
            print( f"[PresentationAPIClient] Response: {input_tokens} in, {output_tokens} out, sdk_cost_usd=${sdk_cost_usd:.4f}" )

        return APIResponse(
            content=content, model=model, input_tokens=input_tokens,
            output_tokens=output_tokens, stop_reason=stop_reason,
            sdk_cost_usd=sdk_cost_usd, raw_response=None,
        )

    # =========================================================================
    # Utility Methods
    # =========================================================================

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


# =============================================================================
# Smoke Test
# =============================================================================

def quick_smoke_test():
    """Quick smoke test for PresentationAPIClient (bounded-CC path)."""
    import cosa.utils.util as cu

    cu.print_banner( "PresentationAPIClient Smoke Test (bounded-CC)", prepend_nl=True )

    try:
        print( "Testing claude_agent_sdk import..." )
        if not SDK_AVAILABLE:
            print( "⚠ claude_agent_sdk not installed - skipping bounded-CC tests" )
            return
        print( "✓ claude_agent_sdk available" )

        print( "Testing instantiation..." )
        client = PresentationAPIClient( debug=True )
        assert client.config.content_model is not None
        print( f"✓ Client instantiated (model={client.config.content_model})" )

        print( "Testing APIResponse dataclass..." )
        response = APIResponse(
            content="Test content", model="claude-opus-4-6",
            input_tokens=100, output_tokens=50, stop_reason="end_turn",
        )
        assert response.content == "Test content"
        assert response.sdk_cost_usd == 0.0
        print( "✓ APIResponse dataclass works" )

        print( "Testing CostEstimate (+ SDK telemetry)..." )
        cost = CostEstimate()
        cost.add_usage( "claude-opus-4-6", 1000, 500 )
        cost.add_usage( "claude-haiku-4-5", 2000, 1000 )
        cost.add_sdk_cost( 0.49 )
        assert cost.total_api_calls == 2
        summary = cost.get_summary()
        assert "API Calls: 2" in summary
        assert "Max plan" in summary
        print( f"✓ Cost tracking works: {summary}" )

        print( "Testing live bounded-CC call (Max-plan OAuth — covered cost)..." )

        async def test_live_call():
            return await client.call_for_analysis(
                system_prompt="You are a helpful assistant. Respond briefly.",
                user_message="Say 'Hello, presentation test!' and nothing else.",
                max_tokens=50,
            )

        import asyncio
        response = asyncio.run( test_live_call() )
        print( f"✓ Live bounded-CC call succeeded" )
        print( f"  Response: {response.content[ :100 ]}" )
        print( f"  {client.get_cost_summary()}" )

        print( "\nAll PresentationAPIClient smoke tests passed" )

    except Exception as e:
        print( f"\nSmoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
