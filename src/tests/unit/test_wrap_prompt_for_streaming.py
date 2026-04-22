"""
Unit tests for wrap_prompt_for_streaming (Bug 15 workaround).

Bug 15 — claude-agent-sdk >= 0.1.36 raises ValueError when a plain string
prompt is passed to sdk_query() with options.can_use_tool set. The helper
wraps the prompt as the single-message AsyncIterable shape the SDK requires.

Upstream tracker (unresolved as of 2026-04-17):
    https://github.com/anthropics/claude-code/issues/18735

When upstream lands the fix, delete this test file alongside the helper
in src/cosa/agents/swe_team/hooks.py and revert every call site.
"""

import asyncio

from cosa.agents.swe_team.hooks import wrap_prompt_for_streaming


def _drain( async_gen ):
    """Collect an async generator into a list synchronously (test helper)."""
    async def run():
        return [ msg async for msg in async_gen ]
    return asyncio.run( run() )


def test_yields_exactly_one_message():
    messages = _drain( wrap_prompt_for_streaming( "hello world" ) )
    assert len( messages ) == 1


def test_message_shape():
    messages = _drain( wrap_prompt_for_streaming( "hello world" ) )
    m = messages[ 0 ]
    assert m[ "type" ]                   == "user"
    assert m[ "message" ][ "role" ]      == "user"
    assert m[ "message" ][ "content" ]   == "hello world"
    assert m[ "parent_tool_use_id" ]     is None
    assert isinstance( m[ "session_id" ], str ) and m[ "session_id" ]


def test_session_id_defaults_to_uuid_when_unset():
    messages = _drain( wrap_prompt_for_streaming( "x" ) )
    sid = messages[ 0 ][ "session_id" ]
    # UUID4 canonical form: 8-4-4-4-12 = 36 chars with 4 hyphens
    assert len( sid ) == 36
    assert sid.count( "-" ) == 4


def test_session_id_respects_override():
    messages = _drain( wrap_prompt_for_streaming( "x", session_id="custom-session-123" ) )
    assert messages[ 0 ][ "session_id" ] == "custom-session-123"


def test_two_invocations_get_distinct_default_session_ids():
    a = _drain( wrap_prompt_for_streaming( "a" ) )[ 0 ][ "session_id" ]
    b = _drain( wrap_prompt_for_streaming( "b" ) )[ 0 ][ "session_id" ]
    assert a != b


def test_preserves_long_multiline_prompt():
    long_prompt = "\n".join( f"line {i}" for i in range( 500 ) )
    messages = _drain( wrap_prompt_for_streaming( long_prompt ) )
    assert messages[ 0 ][ "message" ][ "content" ] == long_prompt
    assert len( messages[ 0 ][ "message" ][ "content" ] ) > 3000
