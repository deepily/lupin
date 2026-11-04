"""
An interactive dispatcher session applies the task's max_turns and timeout_seconds.

_run_bounded passed --max-turns and wrapped the read in asyncio.wait_for. _run_interactive passed neither.
So the dispatcher e2e test, which sets max_turns=1 and timeout_seconds=30, ran for 15 minutes.
These cases use a fake SDK client, so no CLI or server is touched.
"""

import asyncio
from unittest.mock import patch

import cosa.orchestration.claude_code.dispatcher as dispatcher_module
from cosa.orchestration.claude_code.dispatcher import ClaudeCodeDispatcher, Task, TaskType

OUTER_CAP_SECONDS = 5


class _FakeOptions:
    """Records the keyword arguments the dispatcher builds its options from."""

    last = None

    def __init__( self, **kwargs ):
        self.kwargs       = kwargs
        _FakeOptions.last = self


class _FakeClient:
    """An SDK client whose response either ends at once or never ends."""

    never_ends = False

    def __init__( self, options=None ):
        self.options = options

    async def __aenter__( self ):
        return self

    async def __aexit__( self, *exc ):
        return False

    async def query( self, prompt ):
        return None

    async def receive_response( self ):
        if _FakeClient.never_ends: await asyncio.sleep( 3600 )
        return
        yield  # pragma: no cover  # makes this an async generator that yields nothing


def _task( max_turns, timeout_seconds ):
    """Ensures: returns an interactive Task carrying the two limits under test."""
    return Task(
        id="limits-001", project="lupin", prompt="p", type=TaskType.INTERACTIVE,
        max_turns=max_turns, timeout_seconds=timeout_seconds, working_dir="/tmp"
    )


def _dispatch( task ):
    """Ensures: a missing deadline fails the test under an outer cap instead of hanging it."""
    with patch.object( dispatcher_module, "ClaudeSDKClient", _FakeClient ), \
         patch.object( dispatcher_module, "ClaudeAgentOptions", _FakeOptions ):
        dispatcher = ClaudeCodeDispatcher()
        result     = asyncio.run( asyncio.wait_for( dispatcher.dispatch( task ), timeout=OUTER_CAP_SECONDS ) )
    return dispatcher, result


def test_the_task_max_turns_reaches_the_sdk_options():
    _FakeClient.never_ends = False
    _dispatch( _task( max_turns=1, timeout_seconds=30 ) )
    assert _FakeOptions.last.kwargs[ "max_turns" ] == 1


def test_a_different_max_turns_is_passed_through_unchanged():
    _FakeClient.never_ends = False
    _dispatch( _task( max_turns=7, timeout_seconds=30 ) )
    assert _FakeOptions.last.kwargs[ "max_turns" ] == 7


def test_a_session_that_outlives_timeout_seconds_fails_with_a_timeout_result():
    _FakeClient.never_ends = True
    try:
        dispatcher, result = _dispatch( _task( max_turns=1, timeout_seconds=0.2 ) )
    finally:
        _FakeClient.never_ends = False
    assert result.success is False
    assert result.error == "Task timed out after 0.2s"
    assert result.exit_code == -1
    assert "limits-001" not in dispatcher.active_sessions


def test_a_session_inside_the_deadline_still_reports_no_result_when_none_arrives():
    _FakeClient.never_ends = False
    dispatcher, result = _dispatch( _task( max_turns=1, timeout_seconds=30 ) )
    assert result.error == "No result received"
    assert "limits-001" not in dispatcher.active_sessions
