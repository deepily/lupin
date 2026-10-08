#!/usr/bin/env python3
"""
Raise an error ResultMessage as a failure that carries the CLI's own text.

The SDK re-raises a failed call with only the result's subtype ("success"), after it has
already yielded the error ResultMessage. Reading that message is the one place the CLI's
text and errors list are still available.
"""


def raise_error_result( message, label: str, log ):
    """Ensures: logs and raises RuntimeError naming the subtype, the CLI text and the errors."""
    text   = str( message.result )[ :500 ] if message.result else "no text"
    if message.errors: text += f" (errors: {'; '.join( message.errors )[ :500 ]})"
    reason = f"Claude Code returned an error result: {message.subtype}: {text}"
    log.error( f"[{label}] {reason}" )
    raise RuntimeError( reason )
