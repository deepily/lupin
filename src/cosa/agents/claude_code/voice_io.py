"""
Voice I/O wrapper for Claude Code agent.

Thin wrapper around consolidated voice_io module with
Claude Code-specific defaults.
"""

from cosa.agents.utils.voice_io import (
    notify,
    ask_yes_no,
    get_input,
    choose
)

__all__ = [ "notify", "ask_yes_no", "get_input", "choose" ]
