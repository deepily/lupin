"""
Smoke tests for the agentic command disambiguation confirmation loop.

Tests _confirm_agentic_routing() in TodoFifoQueue — the voice prompt
that asks users to confirm or switch the detected agentic command.

Uses mock pattern: mock the queue to avoid heavy __init__, mock
notify_user_sync for responses. All offline: no server, no LLM.

Created: 2026-02-17 (Session 221 — Smoke Test Coverage Audit)
Converted to Pattern A: 2026-02-17 (Session 222 — Consistency Cleanup)
"""

import json
from unittest.mock import MagicMock, patch

from cosa.cli.notification_models import NotificationResponse
from cosa.rest.todo_fifo_queue import TodoFifoQueue


def _make_mock_queue():
    """Lightweight mock of TodoFifoQueue — avoids heavy __init__."""
    queue       = MagicMock()
    queue.debug = False
    queue.PRODUCT_NAMES = TodoFifoQueue.PRODUCT_NAMES
    queue._confirm_agentic_routing = TodoFifoQueue._confirm_agentic_routing.__get__( queue )
    return queue


def _make_response( response_value=None, exit_code=0, status="responded", is_timeout=False ):
    """Build a NotificationResponse with sensible defaults."""
    return NotificationResponse(
        response_value = response_value,
        exit_code      = exit_code,
        status         = status,
        is_timeout     = is_timeout,
    )


def quick_smoke_test():
    """
    Quick smoke test for agentic disambiguation confirmation loop.

    Requires:
        - cosa.rest.todo_fifo_queue importable
        - cosa.cli.notification_models importable

    Ensures:
        - Confirming detected command returns same command
        - Switching to different command returns new command
        - Cancel returns None
        - Timeout returns original command as safe default
        - Returns True on success
    """
    print( "\n" + "=" * 70 )
    print( "  Agentic Disambiguation Smoke Test" )
    print( "=" * 70 )

    try:
        queue = _make_mock_queue()
        cmd   = "agent router go to deep research"
        name  = TodoFifoQueue.PRODUCT_NAMES[ cmd ]

        with patch( "cosa.rest.todo_fifo_queue.notify_user_sync" ) as mock_notify:

            # 1. Confirm detected command
            print( "\n1. Confirm detected command..." )
            mock_notify.return_value = _make_response(
                response_value=json.dumps( { "answers": { "Command": name } } )
            )
            result = queue._confirm_agentic_routing( cmd, "", "u", "u@e.com", "q" )
            assert result == cmd
            print( "   PASS: Confirm returns original command" )

            # 2. Switch to different command
            print( "2. Switch to different command..." )
            podcast_cmd  = "agent router go to podcast generator"
            podcast_name = TodoFifoQueue.PRODUCT_NAMES[ podcast_cmd ]
            mock_notify.return_value = _make_response(
                response_value=json.dumps( { "answers": { "Command": podcast_name } } )
            )
            result = queue._confirm_agentic_routing( cmd, "", "u", "u@e.com", "podcast" )
            assert result == podcast_cmd
            print( "   PASS: Switch returns new command" )

            # 3. Cancel returns None
            print( "3. Cancel returns None..." )
            mock_notify.return_value = _make_response(
                response_value=json.dumps( { "answers": { "Command": "Cancel" } } )
            )
            result = queue._confirm_agentic_routing( cmd, "", "u", "u@e.com", "cancel test" )
            assert result is None
            print( "   PASS: Cancel returns None" )

            # 4. Timeout returns original command
            print( "4. Timeout returns original..." )
            mock_notify.return_value = _make_response(
                response_value=None, exit_code=2, status="expired", is_timeout=True,
            )
            result = queue._confirm_agentic_routing( cmd, "", "u", "u@e.com", "timeout test" )
            assert result == cmd
            print( "   PASS: Timeout returns original command" )

        print( "\n  ALL AGENTIC DISAMBIGUATION SMOKE TESTS PASSED (4/4)" )
        return True

    except Exception as e:
        print( f"\n  FAIL: {e}" )
        import traceback
        traceback.print_exc()
        return False


def test_agentic_disambiguation():
    """Pytest entry point."""
    assert quick_smoke_test()


if __name__ == "__main__":
    quick_smoke_test()
