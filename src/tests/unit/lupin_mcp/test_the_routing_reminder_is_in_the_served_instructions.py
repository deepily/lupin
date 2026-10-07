#!/usr/bin/env python3
"""
Unit test: the interactive-tool routing rule is in the served `instructions`.

`_routing_reminder()` (hook_common) is composed into the cosa-voice server's `instructions` payload under "## Interactive Tool Routing".
The TTS Contract section does not carry it, so that one call is its only route to the caller.
Before this test, deleting the call reddened nothing.

Requires:
    - LUPIN_ROOT names the tree under test (or the cwd is that tree)

Ensures:
    - the exact text `_routing_reminder()` returns appears in `mcp.instructions`
    - it appears under the "## Interactive Tool Routing" heading, once
"""
import os
import sys

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )


def test_the_routing_reminder_text_is_in_the_served_instructions():
    """
    Requires:
        - cosa_voice_mcp imports `_routing_reminder` from hook_common

    Ensures:
        - the full reminder text is a substring of the registered server instructions
    """
    import lupin_mcp.cosa_voice_mcp as m
    from lupin_cli.claude_code.hooks.lib.hook_common import _routing_reminder

    reminder = _routing_reminder()
    assert reminder.strip() != "", "the reminder must not be empty, or the substring check proves nothing"
    assert reminder in m.mcp.instructions


def test_the_routing_reminder_sits_under_the_interactive_tool_routing_heading():
    """
    Ensures:
        - the heading occurs exactly once and the reminder follows it directly
    """
    import lupin_mcp.cosa_voice_mcp as m
    from lupin_cli.claude_code.hooks.lib.hook_common import _routing_reminder

    heading = "## Interactive Tool Routing\n\n"
    assert m.mcp.instructions.count( heading ) == 1
    assert m.mcp.instructions.split( heading )[ 1 ].startswith( _routing_reminder() )
