"""
Unit test for notify_user_sync.py connect-timeout split.

REGRESSION GUARD for the 2026-04-30 22:15-EDT all-suite test failure
(Cluster F in 2026.05.01-postmortem-2026.04.30-2215-edt-all-test-run.md).

The bug: `_send_sync_notification` called `requests.post(..., timeout=N)`
with a single total-timeout. When LUPIN_API_URL pointed at an unreachable
host (the idle_waiter smoke test does this on purpose), the OS-level TCP
SYN retry could dominate the entire 70s budget. The waiter subprocess
exceeded the test's 15s timeout and got SIGKILL'd.

The fix: split timeout into (connect, read) tuple — fail fast on
unreachable URLs (3s connect) without shrinking the read budget for
legitimate long-running confirmation prompts.

This test asserts requests.post is called with the (3, N+10) shape.
"""

import pytest
from unittest.mock import patch, MagicMock

from lupin_cli.notifications.notify_user_sync import _send_sync_notification
from lupin_cli.notifications.notification_models import (
    NotificationRequest,
    NotificationType,
    NotificationPriority,
    ResponseType,
)


@pytest.fixture
def basic_request():
    """A minimal valid NotificationRequest with timeout_seconds=60."""
    return NotificationRequest(
        message          = "test message",
        notification_type= NotificationType.TASK,
        priority         = NotificationPriority.MEDIUM,
        response_type    = ResponseType.YES_NO,
        response_default = "no",
        timeout_seconds  = 60,
        sender_id        = "test.unit@lupin.deepily.ai",
        target_user      = "test@example.com",
    )


def test_requests_post_called_with_split_connect_read_timeout( basic_request ):
    """
    The fix: timeout argument to requests.post must be a 2-tuple
    (connect_timeout, read_timeout) where connect_timeout is short (3s)
    and read_timeout = timeout_seconds + 10.

    Pre-fix this was a single int (timeout_seconds + 10 = 70), causing
    unreachable-URL waits to consume the full read-budget on TCP SYN retry.
    """
    mock_response          = MagicMock()
    mock_response.status_code = 500   # short-circuit before SSE path
    mock_response.text     = "test error"

    with patch( "lupin_cli.notifications.notify_user_sync.requests.post", return_value=mock_response ) as mock_post:
        _send_sync_notification(
            request      = basic_request,
            server_url   = None,
            debug        = False,
            api_key      = "test-key",
            base_url     = "http://localhost:7999",
            env          = "test",
            bearer_token = None,
        )

    assert mock_post.called, "requests.post was never invoked"

    # Inspect kwargs — fix is on the timeout= keyword
    call_kwargs = mock_post.call_args.kwargs
    timeout = call_kwargs[ "timeout" ]

    assert isinstance( timeout, tuple ), (
        f"timeout must be a (connect, read) tuple after the 2026-05-01 fix, "
        f"got {type(timeout).__name__}: {timeout!r}"
    )
    assert len( timeout ) == 2, (
        f"timeout tuple must be 2-element (connect, read), got {len(timeout)}"
    )

    connect_timeout, read_timeout = timeout

    assert connect_timeout == 3, (
        f"connect_timeout must be 3 (fast-fail on unreachable URLs), got {connect_timeout}"
    )
    # read_timeout = request.timeout_seconds + 10 = 60 + 10 = 70
    assert read_timeout == 70, (
        f"read_timeout must be request.timeout_seconds + 10 = 70, got {read_timeout}"
    )


def test_requests_post_read_timeout_scales_with_request_timeout():
    """
    The read-timeout must follow request.timeout_seconds (not a constant) so
    long-running confirmation prompts (180s) still get adequate read budget.
    """
    long_request = NotificationRequest(
        message          = "long-running confirmation",
        notification_type= NotificationType.TASK,
        priority         = NotificationPriority.HIGH,
        response_type    = ResponseType.YES_NO,
        response_default = "no",
        timeout_seconds  = 180,
        sender_id        = "test.unit@lupin.deepily.ai",
        target_user      = "test@example.com",
    )

    mock_response          = MagicMock()
    mock_response.status_code = 500
    mock_response.text     = "test error"

    with patch( "lupin_cli.notifications.notify_user_sync.requests.post", return_value=mock_response ) as mock_post:
        _send_sync_notification(
            request      = long_request,
            server_url   = None,
            debug        = False,
            api_key      = "test-key",
            base_url     = "http://localhost:7999",
            env          = "test",
            bearer_token = None,
        )

    timeout = mock_post.call_args.kwargs[ "timeout" ]
    connect_timeout, read_timeout = timeout

    assert connect_timeout == 3
    assert read_timeout == 190  # 180 + 10
