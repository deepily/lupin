"""
What the podcast and presentation bounded-CC clients share.

Both run text synthesis through the in-process Claude Agent SDK. Each client keeps its own
_call_api, because the two differ. The presentation client leaves stop_reason as None until a
result reports one, so a missing signal is not read as a clean finish. The podcast client starts
it at "end_turn".
"""

import logging
from dataclasses import dataclass


@dataclass
class BoundedCCCostEstimate:
    """Token and SDK-cost tallies for one client; subclasses add the price table and add_usage."""

    total_input_tokens  : int   = 0
    total_output_tokens : int   = 0
    total_api_calls     : int   = 0
    estimated_cost_usd  : float = 0.0
    total_sdk_cost_usd  : float = 0.0

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


class BoundedCCClientBase:
    """
    Construction, typed calls and strict JSON output for a bounded-CC client.

    A subclass sets CONFIG_CLASS, COST_ESTIMATE_CLASS, BANNER_NOUN, BANNER_FIELD,
    JSON_MODEL_FIELD, the label and _logger, and defines _call_api and _recover_json.
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
            - with debug, prints two banner lines naming the class label and the banner-field model

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
        self.cost_estimate = self.COST_ESTIMATE_CLASS()

        if self.debug:
            print( f"[{self.LABEL}] Bounded-CC mode (in-process sdk_query, Max-plan OAuth)" )
            print( f"[{self.LABEL}] {self.BANNER_NOUN} model: {getattr( self.config, self.BANNER_FIELD )}" )

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
