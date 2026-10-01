"""
The one door the judge harness uses to reach a model (plan 1, section 5, step 0).

Bounded Claude Code: in-process sdk_query with tools=[], so the Max plan covers the cost and the
model can only emit text. The firewalled per-token SDK is never used here. Bounded CC has no
temperature setting, so callers get determinism from strict parsing and repeat-run checks.
"""

import asyncio
import hashlib
import secrets

from claude_agent_sdk import ClaudeAgentOptions, AssistantMessage, ResultMessage, TextBlock, query as sdk_query

# With tools=[] there is nothing to permit. "plan" would put the model in plan mode and change
# what it writes (podcast_generator/api_client.py documents the failure), so it is "default".
PERMISSION_MODE = "default"
MAX_TURNS       = 1
NO_TOOLS        = []
TIMEOUT_SECONDS = 600


class ModelCallError( Exception ):
    """A model call returned nothing usable or raised."""


def prompt_version( name, *parts ):
    """
    Derive a prompt version from the text and code that make the prompt, so it cannot go stale.

    Requires:
        - name is a short label; parts are the strings (prompt text, parser source) to hash

    Ensures:
        - returns "<name>-<10 hex digits>" and a change to any part changes it
    """
    return name + "-" + hashlib.sha256( "\0".join( parts ).encode( "utf-8" ) ).hexdigest()[ :10 ]


def new_suffix( *texts ):
    """
    Return a random tag suffix that occurs in none of the given texts.

    Requires:
        - texts are the strings that will sit between the tags

    Ensures:
        - a closing tag built with this suffix cannot be forged by anything in texts
    """
    while True:
        suffix = secrets.token_hex( 4 )
        if not any( suffix in text for text in texts ): return suffix


def wrap( label, suffix, body ):
    """Return body between an opening and a closing tag named label_suffix."""
    return f"<{label}_{suffix}>\n{body}\n</{label}_{suffix}>"


async def complete( model, system_prompt, user_prompt, query_fn=None, timeout_seconds=TIMEOUT_SECONDS ):
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
        - ModelCallError if the call raises, times out, ends in an error result, or returns no text
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

    async def collect():
        async for message in query_fn( prompt=user_prompt, options=options ):
            if isinstance( message, AssistantMessage ):
                parts.extend( block.text for block in message.content if isinstance( block, TextBlock ) )
            elif isinstance( message, ResultMessage ) and message.is_error:
                raise ModelCallError( f"model call to {model} ended in an error result: {message.subtype}" )

    try:
        await asyncio.wait_for( collect(), timeout_seconds )
    except ModelCallError:
        raise
    except asyncio.TimeoutError as e:
        raise ModelCallError( f"model call to {model} timed out after {timeout_seconds}s" ) from e
    except Exception as e:
        raise ModelCallError( f"model call to {model} failed: {e}" ) from e
    text = "".join( parts ).strip()
    if not text: raise ModelCallError( f"model call to {model} returned no text" )
    return text
