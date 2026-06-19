#!/usr/bin/env python3
"""
Unit tests for cosa.agents.notification_proxy.voice_io.

voice_io.notify() is a thin wrapper that builds a kwargs dict and
delegates to the shared cosa.agents.utils.sync_notify.notify helper
(imported into this module as _sync_notify). All delegation is
boundary-mocked here → zero network / notification side effects.
"""

from unittest.mock import patch

import cosa.agents.notification_proxy.voice_io as voice_io
from cosa.agents.notification_proxy.cosa_interface import SENDER_ID


class TestNotify:
    """notify() forwards to _sync_notify, conditionally adding optional kwargs."""

    def test_defaults_omit_optional_kwargs( self ):
        """
        Requires:
            - _sync_notify is patched (no real notification is sent)

        Ensures:
            - with host/port/target_user left as None, only the four base
              kwargs (message, sender_id, priority, debug) are forwarded
            - the wrapper returns whatever _sync_notify returns
            - covers the FALSE arm of all three optional-kwarg guards
        """
        with patch.object( voice_io, "_sync_notify", return_value=True ) as mock_notify:
            result = voice_io.notify( "hello" )

        assert result is True
        mock_notify.assert_called_once_with(
            message   = "hello",
            sender_id = SENDER_ID,
            priority  = "low",
            debug     = False,
        )

    def test_all_optionals_included( self ):
        """
        Ensures:
            - when host, port, and target_user are all provided, each is
              forwarded to _sync_notify alongside the base kwargs
            - priority/debug overrides are forwarded
            - covers the TRUE arm of all three optional-kwarg guards
            - the wrapper returns _sync_notify's (False) return value verbatim
        """
        with patch.object( voice_io, "_sync_notify", return_value=False ) as mock_notify:
            result = voice_io.notify(
                "status",
                priority    = "high",
                host        = "example.org",
                port        = 8123,
                target_user = "user@lupin.deepily.ai",
                debug       = True,
            )

        assert result is False
        mock_notify.assert_called_once_with(
            message     = "status",
            sender_id   = SENDER_ID,
            priority    = "high",
            debug       = True,
            host        = "example.org",
            port        = 8123,
            target_user = "user@lupin.deepily.ai",
        )
