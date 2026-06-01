#!/usr/bin/env python3
"""
Unit tests for cosa.agents.notification_proxy.cosa_interface.

Covers the SENDER_ID constant that identifies this agent's own
status notifications on the commons / notification bus.
"""

import cosa.agents.notification_proxy.cosa_interface as ci


class TestSenderId:
    """SENDER_ID is the stable identity string for proxy self-notifications."""

    def test_sender_id_value( self ):
        """
        Requires:
            - the cosa_interface module is importable

        Ensures:
            - SENDER_ID equals the canonical proxy sender address
        """
        assert ci.SENDER_ID == "notification.proxy@lupin.deepily.ai"

    def test_sender_id_is_nonempty_str( self ):
        """
        Ensures:
            - SENDER_ID is a non-empty string (usable as a bus identity)
        """
        assert isinstance( ci.SENDER_ID, str )
        assert ci.SENDER_ID != ""
