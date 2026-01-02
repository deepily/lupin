"""
CoSA Voice MCP Server - Voice I/O bridge for Claude Code.

This module provides MCP tools for voice-based notifications and conversations
between Claude Code and the CoSA/Lupin notification system.

Tools:
    - converse(): Speak to user, wait for voice/text response (blocking)
    - notify(): Announce to user without waiting (fire-and-forget)
    - ask_yes_no(): Quick yes/no decision (convenience wrapper)
    - get_session_info(): Get current session identification

Configuration:
    MCP_PROJECT is set by your MCP JSON config's env section, not manually.
    Example: { "env": { "MCP_PROJECT": "lupin" } }
"""

__version__ = "0.1.0"
