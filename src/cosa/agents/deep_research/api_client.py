#!/usr/bin/env python3
"""
Bounded-CC research client for the COSA Deep Research Agent.

BOUNDED-CC MIGRATION (Phase 3 — 2026-06-18)
===========================================
This client was migrated from the direct firewalled Anthropic SDK
(`AsyncAnthropic.messages.create`) to the **in-process Claude Agent SDK**
(`claude_agent_sdk.query`), matching the shipped BFE/TFE + Podcast bounded-CC
pattern (ratified D-DR1 Option X). Every LLM-driven research call now runs on
the Max-subscription OAuth path.

This is a COST-SHIFT, NOT "free": the SDK still reports `total_cost_usd`
telemetry per call, but that spend is covered by the fixed Max plan — the
firewalled Anthropic console balance does not move (D8). See:
  - Scope:        src/rnd/v0.1.8/2026.06.18-bounded-cc-d1d9-ratification-package.md (§2)
  - Ratification: src/rnd/v0.1.8/2026.06.18-bounded-cc-d1d9-ratification-package.md (D1–D9)
  - Cost model:   src/docs/cost-model-bounded-cc-vs-firewalled-sdk.md

Web search migration (the DR-specific complexity vs Podcast)
------------------------------------------------------------
The native Anthropic `web_search_20250305` server tool is replaced by Claude
Code's built-in **WebSearch + WebFetch** tools (bounded-CC tool surface). The
downstream contract is preserved BY CONSTRUCTION: the orchestrator and parsers
consume ONLY `APIResponse.content` (the model's text) — they never read the
API's `web_search_tool_result` blocks. The subagent is prompted to write its
sources/citations INTO its text findings (parsed by `parse_subagent_response`),
so swapping the search mechanism leaves the consumed contract identical.

ApiResourceManager retirement on the bounded path
-------------------------------------------------
The legacy `get_arm().acquire/record_call( "anthropic_web_search" )` rate-limit
dance governed Anthropic's 30,000-tokens/minute web-search cap. On the bounded
path web search rides CC's WebSearch (Max-plan rolling-window governs instead),
so that cap no longer applies and the ARM acquire/record_call is dropped from
the call path. The ARM singleton itself is untouched (no other caller of the
`anthropic_web_search` provider exists; pool-status reporting is unaffected).

NOTE: `ClaudeAgentOptions` exposes no per-call `temperature`, so the historical
per-call sampling temperature is folded into the system prompt as a creativity
steer (see `_temperature_to_steer`). Extended thinking maps 1:1 onto the SDK's
`max_thinking_tokens` option.
"""

import json
import logging
from typing import Optional, Any
from dataclasses import dataclass, field

from .config import ResearchConfig
from .cost_tracker import CostTracker, BudgetExceededError
from .rate_limiter import WebSearchRateLimiter

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

# Historical export-compat alias. Before the bounded-CC migration this flag
# gated the `anthropic` SDK import; the firewalled Anthropic path is retired,
# so it now mirrors SDK availability for any legacy importer.
ANTHROPIC_AVAILABLE = SDK_AVAILABLE

logger = logging.getLogger( __name__ )


# =============================================================================
# Historical firewalled-key constants (retained for export compatibility).
#
# The bounded-CC client authenticates via Max-plan OAuth inside `sdk_query`
# and reads NO API key. These names are kept only because `__init__.py` still
# re-exports them; they no longer drive any code path.
# =============================================================================
ENV_VAR_NAME  = "ANTHROPIC_API_KEY_FIREWALLED"   # historical — unused on the bounded path
KEY_FILE_NAME = "anthropic-api-key-firewalled"   # historical — unused on the bounded path


# =============================================================================
# Bounded-CC tool surfaces + permission mode
# =============================================================================
# Lead agent does planning / synthesis only — pure text reasoning, no search.
LEAD_TOOLS = []

# Research subagents need live web access. The native Anthropic web_search tool
# maps onto CC's built-in WebSearch (issue queries) + WebFetch (read a page).
SUBAGENT_TOOLS = [ "WebSearch", "WebFetch" ]

# Two modes, chosen by whether the call has TOOLS — because "plan" does two very
# different things depending on that.
#
# A TOOL-USING call (the research subagents, WebSearch/WebFetch): "plan" is a real
# read-only guard and the tools still work. Verified by the BFE Lead agent, which
# runs Read/Glob/Grep/Bash under "plan". Unchanged.
#
# A NO-TOOL call (the lead agent, LEAD_TOOLS = []): "plan" is not a guard at all —
# with nothing permittable there is nothing to restrict — but it still changes what
# the model PRODUCES. Asked to synthesise a report it writes a plan FOR a report,
# and a strict parser correctly rejects the prose. That is not hypothetical: podcast
# hit it 2026-08-04 (5c45edf6, "no recoverable JSON object", read as a flaky model
# for most of a day) and presentation hit it the same night (f67189c3, job
# pr-62254a7f, "Outline generation returned no usable entries"). Deep research is
# the third instance of the same shape and is fixed here BEFORE it bit anyone —
# no failure of this agent has been observed, so this removes an exposure rather
# than repairing an outage.
RESEARCH_PERMISSION_MODE_WITH_TOOLS = "plan"
RESEARCH_PERMISSION_MODE_NO_TOOLS   = "default"


def _temperature_to_steer( temperature: float ) -> str:
    """
    Translate a legacy sampling temperature into a system-prompt steer.

    `ClaudeAgentOptions` exposes no per-call temperature, so the historical
    per-call value is folded into the system prompt as a qualitative creativity
    instruction.

    Requires:
        - temperature is a float

    Ensures:
        - returns a non-empty steer string for clearly-creative (>= 0.9) or
          clearly-precise (<= 0.5) temperatures
        - returns "" for mid-range temperatures (no steer needed)

    Args:
        temperature: The legacy sampling temperature (typically 0.0–1.0)

    Returns:
        str: A creativity-steer sentence, or "" when no steer is warranted
    """
    if temperature >= 0.9:
        return "Be expansive and creative in your reasoning; explore multiple angles."
    if temperature <= 0.5:
        return "Be precise, literal, and deterministic; avoid speculation."
    return ""


def extract_json_object( text: str ) -> dict:
    """
    Robustly recover a single JSON object from a (possibly chatty) completion.

    D6-STRICT (Deep Research): bounded-CC `sdk_query` may wrap JSON in markdown
    fences or surround it with prose. This recovers the object robustly but
    FAILS LOUD — it never silently returns a default. A missing/blank/parse-failed
    object is a real failure for downstream structured consumers.

    Recovery order:
        1. Strip ```json / ``` fences, then `json.loads` the remainder.
        2. Fall back to the first balanced { ... } span and `json.loads` it.

    Requires:
        - text is a string

    Ensures:
        - returns a dict parsed from the first recoverable JSON object

    Raises:
        - ValueError if text is blank or no valid JSON object can be recovered
    """
    if text is None or not text.strip():
        raise ValueError( "Cannot extract JSON from empty/blank response" )

    content = text.strip()

    # Strip a leading ```json / ``` fence and any trailing ```
    if content.startswith( "```json" ):
        content = content[ 7: ]
    elif content.startswith( "```" ):
        content = content[ 3: ]
    if content.endswith( "```" ):
        content = content[ :-3 ]
    content = content.strip()

    # Attempt 1: the (de-fenced) body is itself JSON
    try:
        return json.loads( content )
    except json.JSONDecodeError:
        pass

    # Attempt 2: scan for the first balanced { ... } span and parse that
    start = content.find( "{" )
    if start != -1:
        depth = 0
        for idx in range( start, len( content ) ):
            char = content[ idx ]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    candidate = content[ start : idx + 1 ]
                    try:
                        return json.loads( candidate )
                    except json.JSONDecodeError:
                        break

    raise ValueError( "Response did not contain a recoverable JSON object" )


@dataclass
class APIResponse:
    """
    Structured response from a bounded-CC research call.

    Contains the response text, token usage, stop reason, and the SDK-reported
    `sdk_cost_usd` (D8 telemetry — covered by the Max plan, not billed per-token).

    `tool_use` / `search_results` are retained for shape compatibility with the
    pre-migration dataclass; they are NOT consumed downstream (the orchestrator
    reads only `content`) and stay empty on the bounded path.
    """
    content        : str
    model          : str
    input_tokens   : int
    output_tokens  : int
    stop_reason    : str
    sdk_cost_usd   : float = 0.0
    tool_use       : list  = field( default_factory=list )
    search_results : list  = field( default_factory=list )
    raw_response   : Any   = None


class ResearchAPIClient:
    """
    In-process bounded-CC research client (Claude Agent SDK / Max-plan OAuth).

    Requires:
        - claude_agent_sdk is installed (SDK_AVAILABLE is True)

    Ensures:
        - Async execution for parallel subagent support
        - Integrated token-estimate cost tracking (CostTracker) + SDK cost telemetry
        - Web access for subagents via CC WebSearch/WebFetch
        - Model-appropriate routing (Opus for lead, Sonnet for subagents)

    No API key is required: `sdk_query` authenticates via the Claude Code /
    Max-subscription OAuth session, NOT a firewalled API key. This is the
    zero-per-token bounded path.
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
        Initialize the bounded-CC research client.

        Requires:
            - claude_agent_sdk is installed

        Ensures:
            - Builds a rate limiter (retained for CLI time-estimate UX only;
              no longer in the LLM call path under bounded CC)

        Args:
            config: Research configuration (uses defaults if None)
            cost_tracker: Cost tracker for usage recording (optional)
            api_key: Retained for signature compatibility — IGNORED on the
                bounded path (OAuth via sdk_query; no key is read)
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

        self.config       = config or ResearchConfig()
        self.cost_tracker = cost_tracker
        self.debug        = debug
        self.verbose      = verbose

        # Rate limiter retained for CLI progress/time-estimate UX (estimate_total_time).
        # NOT in the LLM call path under bounded CC — web search rides CC WebSearch,
        # governed by the Max-plan rolling window, not Anthropic's 30k-tokens/min cap.
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
            print( f"[ResearchAPIClient] Bounded-CC mode (in-process sdk_query, Max-plan OAuth)" )
            print( f"[ResearchAPIClient] Models: lead={self.config.lead_model}, subagent={self.config.subagent_model}" )

    async def _rate_limit_notify( self, message: str, priority: str ) -> None:
        """
        Callback for the rate limiter to notify the user about delays.

        Uses voice_io if available, otherwise prints to console.

        Args:
            message: Notification message
            priority: Notification priority (low, medium, high)
        """
        try:
            from . import voice_io
            await voice_io.notify( message, priority=priority )
        except Exception:
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

        Lead agent handles planning, synthesis, and coordination tasks — pure
        text reasoning, no web search (tools=[]).

        Args:
            system_prompt: System prompt for the agent
            user_message: User message/query
            call_type: Type of call for cost tracking
            use_extended_thinking: Enable extended thinking (→ max_thinking_tokens)
            max_tokens: Retained for signature parity (unused on the bounded path)
            temperature: Folded into the system-prompt creativity steer

        Returns:
            APIResponse: Structured response with content and usage
        """
        return await self._call_sdk(
            model                 = self.config.lead_model,
            system_prompt         = system_prompt,
            user_message          = user_message,
            call_type             = call_type,
            tools                 = LEAD_TOOLS,
            use_extended_thinking = use_extended_thinking,
            temperature           = temperature,
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

        Subagents handle focused research with live web access via CC's
        WebSearch + WebFetch tools. (On the bounded path there is no Anthropic
        30k-tokens/min web-search cap — the Max-plan rolling window governs — so
        the legacy ApiResourceManager acquire/record_call dance is dropped.)

        Args:
            system_prompt: System prompt for the subagent
            user_message: The subquery to research
            subquery_index: Index of this subquery (for tracking)
            call_type: Type of call for cost tracking
            use_web_search: Enable web search tools (WebSearch/WebFetch)
            max_tokens: Retained for signature parity (unused on the bounded path)
            temperature: Folded into the system-prompt creativity steer

        Returns:
            APIResponse: Structured response with content
        """
        tools = SUBAGENT_TOOLS if use_web_search else LEAD_TOOLS

        return await self._call_sdk(
            model                 = self.config.subagent_model,
            system_prompt         = system_prompt,
            user_message          = user_message,
            call_type             = call_type,
            tools                 = tools,
            subquery_index        = subquery_index,
            use_extended_thinking = False,  # Subagents don't use extended thinking
            temperature           = temperature,
        )

    async def call_with_json_output(
        self,
        system_prompt: str,
        user_message: str,
        model: Optional[ str ] = None,
        call_type: str = "structured",
        max_tokens: int = 4096
    ) -> dict:
        """
        Call the model expecting a JSON object (D6-STRICT, fail-loud).

        Ensures:
            - Robustly recovers a JSON object from chatty/fenced output
            - Raises ValueError on blank output or unrecoverable JSON
              (never silently returns a default)

        Args:
            system_prompt: System prompt (should request JSON output)
            user_message: User message
            model: Model to use (defaults to lead model)
            call_type: Type of call for cost tracking
            max_tokens: Retained for signature parity (unused on the bounded path)

        Returns:
            dict: Parsed JSON response

        Raises:
            ValueError: if the response is blank or not valid JSON
        """
        response = await self._call_sdk(
            model         = model or self.config.lead_model,
            system_prompt = system_prompt,
            user_message  = user_message,
            call_type     = call_type,
            tools         = LEAD_TOOLS,
        )

        try:
            return extract_json_object( response.content )
        except ValueError as e:
            logger.error( f"Failed to parse JSON response: {e}" )
            logger.debug( f"Raw content: {response.content!r}" )
            raise

    async def _call_sdk(
        self,
        model: str,
        system_prompt: str,
        user_message: str,
        call_type: str = "unknown",
        tools: Optional[ list ] = None,
        subquery_index: Optional[ int ] = None,
        use_extended_thinking: bool = False,
        temperature: float = 1.0
    ) -> APIResponse:
        """
        Internal bounded-CC call via in-process `sdk_query`.

        Requires:
            - SDK_AVAILABLE is True

        Ensures:
            - Builds ClaudeAgentOptions (model, system_prompt, tools, read-only
              permission, max_turns, optional extended-thinking budget)
            - Folds temperature into the system-prompt creativity steer
            - Concatenates all assistant TextBlocks into the response content
            - Records token usage (CostTracker estimate) + SDK cost telemetry (D8)

        Args:
            model: Model to use
            system_prompt: System prompt
            user_message: User message
            call_type: Type of call for cost tracking
            tools: Bounded-CC tool allow-list (LEAD_TOOLS or SUBAGENT_TOOLS)
            subquery_index: Subquery index for parallel tracking
            use_extended_thinking: Enable extended thinking (→ max_thinking_tokens)
            temperature: Folded into the creativity steer

        Returns:
            APIResponse: Structured response
        """
        steer            = _temperature_to_steer( temperature )
        effective_system = system_prompt or ""
        if steer:
            effective_system = ( effective_system + "\n\n" + steer ).strip()

        effective_tools = tools if tools is not None else LEAD_TOOLS
        option_kwargs = {
            "model"           : model,
            "system_prompt"   : effective_system or None,
            "tools"           : effective_tools,
            # Derived from the tool list, not hardcoded — see the constants above.
            # With no tools "plan" guards nothing and only corrupts the output.
            "permission_mode" : RESEARCH_PERMISSION_MODE_WITH_TOOLS if effective_tools
                                else RESEARCH_PERMISSION_MODE_NO_TOOLS,
            "max_turns"       : self.config.max_research_turns,
        }
        if use_extended_thinking:
            option_kwargs[ "max_thinking_tokens" ] = self.config.extended_thinking_budget

        options = ClaudeAgentOptions( **option_kwargs )

        if self.debug:
            print( f"[ResearchAPIClient] sdk_query {model} for {call_type} (tools={option_kwargs['tools']}, max_turns={self.config.max_research_turns})" )

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

        # Record token-estimate usage via CostTracker (existing cost surface).
        if self.cost_tracker:
            try:
                self.cost_tracker.record_from_response(
                    model          = model,
                    response_usage = {
                        "input_tokens"  : input_tokens,
                        "output_tokens" : output_tokens,
                    },
                    call_type      = call_type,
                    subquery_index = subquery_index,
                )
            except BudgetExceededError:
                raise  # Let budget errors propagate

        if self.debug:
            print( f"[ResearchAPIClient] Response: {input_tokens} in, {output_tokens} out, sdk_cost_usd=${sdk_cost_usd:.4f} (Max-plan telemetry)" )

        return APIResponse(
            content       = content,
            model         = model,
            input_tokens  = input_tokens,
            output_tokens = output_tokens,
            stop_reason   = stop_reason,
            sdk_cost_usd  = sdk_cost_usd,
            raw_response  = None,
        )

    async def close( self ):
        """
        Release client resources.

        No-op under the bounded-CC path: `sdk_query` is stateless (no persistent
        client/connection to close). Retained for API compatibility.
        """
        return None


def quick_smoke_test():
    """Quick smoke test for ResearchAPIClient (bounded-CC path)."""
    import asyncio
    import cosa.utils.util as cu

    cu.print_banner( "ResearchAPIClient Smoke Test (bounded-CC)", prepend_nl=True )

    try:
        # Test 1: SDK availability
        print( "Testing claude_agent_sdk import..." )
        if not SDK_AVAILABLE:
            print( "⚠ claude_agent_sdk not installed - skipping bounded-CC tests" )
            print( "  Install with: pip install claude-agent-sdk" )
            return
        print( "✓ claude_agent_sdk available" )

        # Test 2: JSON extraction helper (D6-STRICT)
        print( "Testing extract_json_object (D6-STRICT)..." )
        assert extract_json_object( '{"a": 1}' ) == { "a": 1 }
        assert extract_json_object( '```json\n{"a": 2}\n```' ) == { "a": 2 }
        assert extract_json_object( 'Here you go:\n{"a": 3}\nThanks!' ) == { "a": 3 }
        for bad in [ "", "   ", "no json here" ]:
            try:
                extract_json_object( bad )
                print( f"✗ Should have raised ValueError for {bad!r}" )
            except ValueError:
                pass
        print( "✓ extract_json_object recovers + fails loud correctly" )

        # Test 3: temperature steer
        print( "Testing _temperature_to_steer..." )
        assert _temperature_to_steer( 1.0 ) != ""
        assert _temperature_to_steer( 0.3 ) != ""
        assert _temperature_to_steer( 0.7 ) == ""
        print( "✓ _temperature_to_steer works" )

        # Test 4: Instantiation
        print( "Testing instantiation..." )
        cost_tracker = CostTracker( session_id="smoke-test", debug=True )
        client = ResearchAPIClient( cost_tracker=cost_tracker, debug=True )
        assert client.config.lead_model is not None
        assert client.config.subagent_model is not None
        print( f"✓ Client instantiated (lead={client.config.lead_model})" )

        # Test 5: APIResponse dataclass
        print( "Testing APIResponse dataclass..." )
        response = APIResponse(
            content       = "Test content",
            model         = "claude-sonnet-4-6",
            input_tokens  = 100,
            output_tokens = 50,
            stop_reason   = "end_turn",
        )
        assert response.content == "Test content"
        assert response.sdk_cost_usd == 0.0
        print( "✓ APIResponse dataclass works" )

        # Test 6: Live bounded-CC call (lead agent, no tools)
        print( "\nTesting live bounded-CC call (Max-plan OAuth)..." )

        async def test_live_call():
            return await client.call_lead_agent(
                system_prompt = "You are a helpful assistant. Respond briefly.",
                user_message  = "Say 'Hello, smoke test!' and nothing else.",
                call_type     = "smoke_test",
            )

        live = asyncio.run( test_live_call() )
        print( f"✓ Live bounded-CC call succeeded" )
        print( f"  Response: {live.content[:100]}" )
        print( f"  Tokens: {live.input_tokens} in, {live.output_tokens} out" )
        print( f"  SDK cost telemetry: ${live.sdk_cost_usd:.4f} (covered by Max plan — not billed)" )

        print( "\n✓ ResearchAPIClient smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
