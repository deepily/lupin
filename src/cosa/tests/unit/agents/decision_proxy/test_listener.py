#!/usr/bin/env python3
"""
Unit tests for cosa.agents.decision_proxy.listener.

DecisionListener extends BaseWebSocketListener, supplying the
decision-proxy event subscription and log prefix. The base __init__ is
patched out (no real WebSocket connection) so we can assert the exact
arguments DecisionListener forwards to super().
"""

from unittest.mock import patch

from cosa.agents.decision_proxy import listener as listener_mod
from cosa.agents.decision_proxy.listener import DecisionListener
from cosa.agents.decision_proxy.config import SUBSCRIBED_EVENTS, DEFAULT_SESSION_ID


def test_log_prefix_is_decision_listener():
    assert DecisionListener.LOG_PREFIX == "[DecisionListener]"


def test_init_forwards_defaults_and_subscribed_events():
    """
    Ensures:
        - DecisionListener wires the decision-proxy SUBSCRIBED_EVENTS into super()
        - default session_id is used when not overridden
    """
    with patch.object( listener_mod.BaseWebSocketListener, "__init__", return_value=None ) as mock_init:
        DecisionListener( email="e@x", password="pw" )

    mock_init.assert_called_once()
    kwargs = mock_init.call_args.kwargs
    assert kwargs[ "email" ] == "e@x"
    assert kwargs[ "password" ] == "pw"
    assert kwargs[ "session_id" ] == DEFAULT_SESSION_ID
    assert kwargs[ "subscribed_events" ] == SUBSCRIBED_EVENTS
    assert kwargs[ "on_event" ] is None


def test_init_forwards_custom_arguments():
    """
    Ensures:
        - all explicitly supplied constructor args are threaded to super()
    """
    callback = lambda event: None
    with patch.object( listener_mod.BaseWebSocketListener, "__init__", return_value=None ) as mock_init:
        DecisionListener(
            email="user",
            password="secret",
            session_id="custom-session",
            on_event=callback,
            host="ws.example.com",
            port=9999,
            debug=True,
            verbose=True,
        )

    kwargs = mock_init.call_args.kwargs
    assert kwargs[ "session_id" ] == "custom-session"
    assert kwargs[ "on_event" ] is callback
    assert kwargs[ "host" ] == "ws.example.com"
    assert kwargs[ "port" ] == 9999
    assert kwargs[ "debug" ] is True
    assert kwargs[ "verbose" ] is True
    assert kwargs[ "subscribed_events" ] == SUBSCRIBED_EVENTS
