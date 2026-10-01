"""
The one door the judge harness uses to reach a model (plan 1, section 5, step 0).

Bounded Claude Code: in-process sdk_query with tools=[], so the Max plan covers the cost and the
model can only emit text. The firewalled per-token SDK is never used here. Bounded CC has no
temperature setting, so callers get determinism from strict parsing and repeat-run checks.
"""

from claude_agent_sdk import ClaudeAgentOptions, AssistantMessage, TextBlock, query as sdk_query

# With tools=[] there is nothing to permit. "plan" would put the model in plan mode and change
# what it writes (podcast_generator/api_client.py documents the failure), so it is "default".
PERMISSION_MODE = "default"
MAX_TURNS       = 1
NO_TOOLS        = []


class ModelCallError( Exception ):
    """A model call returned nothing usable or raised."""


async def complete( model, system_prompt, user_prompt, query_fn=None ):
    """
    Send one prompt to a bounded Claude Code model and return its text.

    Requires:
        - model is a non-empty string naming a model id; there is no default on purpose
        - query_fn, when given, is an async generator function with sdk_query's signature
          ( prompt=..., options=... ), used by tests to stand in for the SDK

    Ensures:
        - tools are disabled, so the model can only write text
        - returns the concatenated text blocks of the assistant messages, stripped
        - the text is never empty

    Raises:
        - ValueError if model is empty
        - ModelCallError if the call raises or returns no text
    """
    if not model: raise ValueError( "model id is required: the harness has no default model" )
    query_fn = sdk_query if query_fn is None else query_fn
    options  = ClaudeAgentOptions(
        model           = model,
        system_prompt   = system_prompt,
        tools           = NO_TOOLS,
        permission_mode = PERMISSION_MODE,
        max_turns       = MAX_TURNS,
    )
    parts = []
    try:
        async for message in query_fn( prompt=user_prompt, options=options ):
            if isinstance( message, AssistantMessage ):
                parts.extend( block.text for block in message.content if isinstance( block, TextBlock ) )
    except Exception as e:
        raise ModelCallError( f"model call to {model} failed: {e}" ) from e
    text = "".join( parts ).strip()
    if not text: raise ModelCallError( f"model call to {model} returned no text" )
    return text
