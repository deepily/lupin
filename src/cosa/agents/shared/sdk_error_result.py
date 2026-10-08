#!/usr/bin/env python3
"""
Raise an error ResultMessage as a failure that carries the CLI's own text.

The SDK re-raises a failed call with only the result's subtype ("success"), after it has
already yielded the error ResultMessage. Reading that message is the one place the CLI's
text and errors list are still available.
"""


def error_result_text( message ) -> str:
    """Ensures: returns the failure text naming the subtype, the CLI text and the errors."""
    text = str( message.result )[ :500 ] if message.result else "no text"
    if message.errors: text += f" (errors: {'; '.join( message.errors )[ :500 ]})"
    return f"Claude Code returned an error result: {message.subtype}: {text}"


def raise_error_result( message, label: str, log ):
    """Ensures: logs and raises RuntimeError naming the subtype, the CLI text and the errors."""
    reason = error_result_text( message )
    log.error( f"[{label}] {reason}" )
    raise RuntimeError( reason )
