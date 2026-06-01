#!/usr/bin/env python3
"""
Unit tests for cosa.agents.decision_proxy.voice_io.

voice_io.notify() builds a kwargs payload and delegates to the shared
sync_notify helper. The helper is mocked at the boundary (zero network /
API spend). Tests cover both arms of each optional-arg branch
(host / port / target_user present vs. absent).
"""

from unittest.mock import patch

from cosa.agents.decision_proxy import voice_io
from cosa.agents.decision_proxy.cosa_interface import SENDER_ID


def test_notify_defaults_omit_optional_kwargs():
    """
    Ensures:
        - default call forwards message/sender_id/priority/debug
        - host/port/target_user are NOT forwarded when left as None
        - the helper's return value is propagated
    """
    with patch.object( voice_io, "_sync_notify", return_value=True ) as mock_notify:
        result = voice_io.notify( "hello" )

    assert result is True
    mock_notify.assert_called_once()
    kwargs = mock_notify.call_args.kwargs
    assert kwargs[ "message" ] == "hello"
    assert kwargs[ "sender_id" ] == SENDER_ID
    assert kwargs[ "priority" ] == "low"
    assert kwargs[ "debug" ] is False
    assert "host" not in kwargs
    assert "port" not in kwargs
    assert "target_user" not in kwargs


def test_notify_forwards_all_optional_kwargs():
    """
    Ensures:
        - every optional arg, when provided, is forwarded to the helper
        - a falsy helper result is propagated unchanged
    """
    with patch.object( voice_io, "_sync_notify", return_value=False ) as mock_notify:
        result = voice_io.notify(
            "status",
            priority="high",
            host="example.com",
            port=7999,
            target_user="user@example.com",
            debug=True,
        )

    assert result is False
    kwargs = mock_notify.call_args.kwargs
    assert kwargs[ "message" ] == "status"
    assert kwargs[ "priority" ] == "high"
    assert kwargs[ "host" ] == "example.com"
    assert kwargs[ "port" ] == 7999
    assert kwargs[ "target_user" ] == "user@example.com"
    assert kwargs[ "debug" ] is True
    assert kwargs[ "sender_id" ] == SENDER_ID
