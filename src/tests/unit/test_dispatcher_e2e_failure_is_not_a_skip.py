"""
A dispatcher failure fails the dispatcher e2e tests instead of skipping them.

The integration file skipped four tests on any failed TaskResult, so a broken dispatcher read
as a quiet pass. These cases drive the real test bodies with a dispatcher double that always
fails. No server, CLI or SDK call is made, so this runs on the dev venue.
"""

import importlib.util

import pytest

import cosa.utils.util as cu
from cosa.orchestration import ClaudeCodeDispatcher, TaskResult

E2E_PATH = cu.get_project_root() + "/src/tests/integration/test_dispatcher_e2e.py"


def _load_e2e():
    """
    Import the integration test module by path.

    Ensures:
        - returns the module object; nothing in it runs until a test body is called
    """
    spec   = importlib.util.spec_from_file_location( "dispatcher_e2e_under_test", E2E_PATH )
    module = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return module


@pytest.fixture
def failing_dispatch( monkeypatch ):
    """
    Replace ClaudeCodeDispatcher.dispatch with a double that always fails.

    Ensures:
        - dispatch returns TaskResult( success=False ) carrying a known error
        - the SDK reports available, so the SDK precondition skip is not the path taken
    """
    async def _failing( self_, task ):
        return TaskResult( task_id=task.id, success=False, error="forced dispatcher failure" )

    monkeypatch.setattr( ClaudeCodeDispatcher, "dispatch", _failing )
    import cosa.orchestration.claude_code.dispatcher as dispatcher_module
    monkeypatch.setattr( dispatcher_module, "SDK_AVAILABLE", True )


@pytest.mark.asyncio
@pytest.mark.parametrize( "class_name, test_name", [
    ( "TestDispatcherE2E",         "test_bounded_task_simple" ),
    ( "TestDispatcherInteractive", "test_interactive_session_basic" ),
    ( "TestDispatcherInteractive", "test_interactive_session_streaming" ),
    ( "TestDispatcherInteractive", "test_interactive_with_notify" ),
] )
async def test_a_dispatcher_failure_fails_the_test_body( failing_dispatch, class_name, test_name ):
    """
    The body raises a failure naming the dispatcher error, not a skip.

    pytest.skip raises a different exception type, so a skip cannot satisfy this assertion.
    """
    module = _load_e2e()
    body   = getattr( getattr( module, class_name )(), test_name )

    with pytest.raises( pytest.fail.Exception, match="forced dispatcher failure" ):
        await body( ClaudeCodeDispatcher(), None, None )


def test_the_failure_skips_are_gone_from_the_file():
    """
    No test in the file skips on a failed result.

    Skips for an absent server, CLI or SDK stay, and none of them names a task failure.
    """
    text = open( E2E_PATH ).read()
    assert "may be config issue" not in text
    assert 'pytest.skip( f"Task failed' not in text


def test_a_successful_result_returns_quietly():
    """The helper returns None for a successful TaskResult."""
    module = _load_e2e()
    assert module._require_dispatch_success( TaskResult( task_id="t", success=True ), "x" ) is None
