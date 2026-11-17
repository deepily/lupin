"""
What the podcast and presentation bounded-CC clients share.

Both run text synthesis through the in-process Claude Agent SDK.
Each client keeps a thin _call_api that names its tools, turn limit and APIResponse; `_call_bounded` runs the call.
The loop that reads the reply stream and records cost is `_collect_reply` here.
Both clients leave stop_reason as None until a result reports one, so a missing signal is not read as a clean finish.
"""

import logging
from dataclasses import dataclass

from cosa.agents.shared.sdk_error_result import raise_error_result


@dataclass
class BoundedCCCostEstimate:
    """Token and SDK-cost tallies for one client; override price_pair to add a price tier."""

    total_input_tokens  : int   = 0
    total_output_tokens : int   = 0
    total_api_calls     : int   = 0
    estimated_cost_usd  : float = 0.0
    total_sdk_cost_usd  : float = 0.0

    # Pricing per million tokens (approximate)
    OPUS_INPUT_PRICE    : float = 15.0
    OPUS_OUTPUT_PRICE   : float = 75.0
    SONNET_INPUT_PRICE  : float = 3.0
    SONNET_OUTPUT_PRICE : float = 15.0

    def price_pair( self, model: str ):
        """
        Pick the per-million-token prices for a model name.

        Requires:
            - model is a string

        Ensures:
            - returns ( input price, output price ): Opus when the name holds "opus", Sonnet for any other name
        """
        if "opus" in model.lower(): return self.OPUS_INPUT_PRICE, self.OPUS_OUTPUT_PRICE
        return self.SONNET_INPUT_PRICE, self.SONNET_OUTPUT_PRICE

    def add_usage( self, model: str, input_tokens: int, output_tokens: int ):
        """
        Add token usage from an LLM call (token-based price estimate).

        Requires:
            - input_tokens and output_tokens are whole numbers of tokens

        Ensures:
            - adds both token counts and one call to the totals
            - adds the cost at the prices price_pair gives for the model to estimated_cost_usd
        """
        self.total_input_tokens  += input_tokens
        self.total_output_tokens += output_tokens
        self.total_api_calls     += 1
        in_price, out_price       = self.price_pair( model )
        self.estimated_cost_usd  += ( input_tokens * in_price / 1_000_000 +
                                      output_tokens * out_price / 1_000_000 )

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


def temperature_to_steer( temperature: float, high: float, low: float, high_steer: str, low_steer: str ) -> str:
    """
    Turn a legacy sampling temperature into a system-prompt creativity steer.

    `ClaudeAgentOptions` exposes no per-call temperature, so each bounded-CC client folds the old
    per-call value into its system prompt as a sentence. The clients differ in where the cut-offs
    sit and in the wording, so both are arguments.

    Requires:
        - temperature, high and low are floats, with low below high
        - high_steer and low_steer are the sentences to use

    Ensures:
        - returns high_steer when temperature >= high
        - returns low_steer when temperature <= low
        - returns "" for a mid-range temperature, where no steer is needed
    """
    if temperature >= high: return high_steer
    if temperature <= low: return low_steer
    return ""


class BoundedCCClientBase:
    """
    Construction, typed calls and strict JSON output for a bounded-CC client.

    A subclass sets CONFIG_CLASS, COST_ESTIMATE_CLASS, BANNER_NOUN, BANNER_FIELD,
    JSON_MODEL_FIELD, the label and _logger. It defines _call_api and _recover_json when it uses
    _call_typed or call_with_json_output. A client that tracks cost elsewhere leaves
    COST_ESTIMATE_CLASS as None, and one with its own banner overrides _banner_model_line.
    """

    CONFIG_CLASS        = None
    COST_ESTIMATE_CLASS = None
    LABEL               = "BoundedCCClient"
    BANNER_NOUN         = "Model"
    BANNER_FIELD        = None
    JSON_MODEL_FIELD    = None
    _logger             = logging.getLogger( __name__ )

    def __init__( self, config, debug, verbose, sdk_available ):
        """
        Set up a client.

        Requires:
            - sdk_available is the importing module's own SDK_AVAILABLE flag, read at call time
            - the class attributes named above are set

        Ensures:
            - self.config is `config`, or CONFIG_CLASS() when None
            - self.debug, self.verbose and self.cost_estimate are set
            - self.cost_estimate is COST_ESTIMATE_CLASS(), or None when that class is None
            - with debug, prints a banner line, then the line _banner_model_line returns, each led by the class label

        Raises:
            - ImportError if the Claude Agent SDK is not installed
        """
        if not sdk_available:
            raise ImportError(
                "claude_agent_sdk not installed. "
                "Install with: pip install claude-agent-sdk"
            )

        self.config  = config or self.CONFIG_CLASS()
        self.debug   = debug
        self.verbose = verbose

        # Cost tracking
        self.cost_estimate = self.COST_ESTIMATE_CLASS() if self.COST_ESTIMATE_CLASS is not None else None

        if self.debug:
            print( f"[{self.LABEL}] Bounded-CC mode (in-process sdk_query, Max-plan OAuth)" )
            print( f"[{self.LABEL}] {self._banner_model_line()}" )

    def _banner_model_line( self ) -> str:
        """
        Name the model for the debug banner.

        Ensures:
            - returns "<BANNER_NOUN> model: <the BANNER_FIELD model>"; a subclass overrides this to say more
        """
        return f"{self.BANNER_NOUN} model: {getattr( self.config, self.BANNER_FIELD )}"

    async def _call_typed( self, model, call_type, system_prompt, user_message, max_tokens, temperature ):
        """
        Make one named call through the subclass's _call_api.

        Requires:
            - model is a model name; call_type names the call in logs and errors

        Ensures:
            - returns what self._call_api( ... ) returns, called with those values as keywords
        """
        return await self._call_api(
            model         = model,
            system_prompt = system_prompt,
            user_message  = user_message,
            max_tokens    = max_tokens,
            temperature   = temperature,
            call_type     = call_type,
        )

    async def _collect_reply( self, stream, model, call_type, assistant_message, text_block, result_message ):
        """
        Read one `sdk_query` stream to its end and record the usage and cost.

        The message classes are arguments because each client module imports them under its own
        name, and its tests replace them there.

        Requires:
            - stream is the async iterator sdk_query returned
            - assistant_message, text_block and result_message are the SDK's classes, or stand-ins

        Ensures:
            - returns ( content, input_tokens, output_tokens, sdk_cost_usd, stop_reason )
            - content is every assistant text block joined and stripped
            - stop_reason is None until a result message reports one; it is never seeded as "end_turn", so a missing signal reads as truncated downstream
            - self.cost_estimate holds the usage and the SDK cost telemetry

        Raises:
            - RuntimeError when a result message is an error, with the failure text and any login hint
        """
        collected     = []
        input_tokens  = 0
        output_tokens = 0
        sdk_cost_usd  = 0.0
        stop_reason   = None

        async for message in stream:
            if isinstance( message, assistant_message ):
                for block in message.content:
                    if isinstance( block, text_block ):
                        collected.append( block.text )
            elif isinstance( message, text_block ):
                collected.append( message.text )
            elif isinstance( message, result_message ):
                if message.is_error: raise_error_result( message, f"{self.LABEL} {call_type}", self._logger )
                usage         = message.usage or {}
                input_tokens  = usage.get( "input_tokens", 0 )
                output_tokens = usage.get( "output_tokens", 0 )
                sdk_cost_usd  = message.total_cost_usd or 0.0
                stop_reason   = message.stop_reason

        self.cost_estimate.add_usage( model=model, input_tokens=input_tokens, output_tokens=output_tokens )
        self.cost_estimate.add_sdk_cost( sdk_cost_usd )

        return "".join( collected ).strip(), input_tokens, output_tokens, sdk_cost_usd, stop_reason

    async def _call_bounded( self, model, system_prompt, user_message, call_type, temperature,
                             steer, sdk, tools, permission_mode, max_turns, response_class ):
        """
        Run one text-synthesis call through the in-process `sdk_query` and wrap the reply.

        The SDK names, the steer rule and the response class are arguments.
        Each client module imports them under its own name, and its tests replace them there.

        Requires:
            - steer is the client's temperature-to-steer function, taking a float and returning a string
            - sdk is ( ClaudeAgentOptions, sdk_query, AssistantMessage, TextBlock, ResultMessage ), or stand-ins
            - response_class takes content, model, input_tokens, output_tokens, stop_reason, sdk_cost_usd, raw_response

        Ensures:
            - folds the steer for temperature into the system prompt
            - builds the options with the given tools, permission mode and turn limit
            - returns response_class with the reply, the usage, the stop reason and the SDK cost
            - with debug, prints the call and the usage, each led by the class label

        Raises:
            - RuntimeError when the result message is an error, as _collect_reply does
        """
        options_class, sdk_query, assistant_message, text_block, result_message = sdk

        effective_system = system_prompt or ""
        steer_text       = steer( temperature )
        if steer_text:
            effective_system = ( effective_system + "\n\n" + steer_text ).strip()

        options = options_class(
            model           = model,
            system_prompt   = effective_system or None,
            tools           = tools,
            permission_mode = permission_mode,
            max_turns       = max_turns,
        )

        if self.debug: print( f"[{self.LABEL}] sdk_query {model} for {call_type} (max_turns={max_turns})" )

        content, input_tokens, output_tokens, sdk_cost_usd, stop_reason = await self._collect_reply(
            sdk_query( prompt=user_message, options=options ), model, call_type,
            assistant_message, text_block, result_message,
        )

        if self.debug: print( f"[{self.LABEL}] Response: {input_tokens} in, {output_tokens} out, sdk_cost_usd=${sdk_cost_usd:.4f}" )

        return response_class(
            content       = content,
            model         = model,
            input_tokens  = input_tokens,
            output_tokens = output_tokens,
            stop_reason   = stop_reason,
            sdk_cost_usd  = sdk_cost_usd,
            raw_response  = None,
        )

    async def call_with_json_output( self, system_prompt: str, user_message: str, max_tokens: int = 4096 ) -> dict:
        """
        Call the model expecting a JSON object, and recover it from chatty output.

        Requires:
            - system_prompt asks for JSON output

        Ensures:
            - calls at temperature 0.5 on the JSON_MODEL_FIELD model
            - returns the object _recover_json finds in the reply

        Raises:
            - ValueError if no JSON object can be recovered; no default is substituted
        """
        response = await self._call_api(
            model         = getattr( self.config, self.JSON_MODEL_FIELD ),
            system_prompt = system_prompt,
            user_message  = user_message,
            max_tokens    = max_tokens,
            temperature   = 0.5,  # low → "precise" steer for structured output
            call_type     = "json_output",
        )

        parsed = self._recover_json( response.content )
        if parsed is None:
            self._logger.error( "Failed to recover JSON object from response" )
            self._logger.debug( f"Raw content: {response.content}" )
            raise ValueError( "Response did not contain a recoverable JSON object" )
        return parsed
