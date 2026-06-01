#!/usr/bin/env python3
"""
Unit tests for cosa.agents.decision_proxy.cosa_interface.

Covers the single SENDER_ID constant that identifies all decision-proxy
notifications and REST submissions.
"""

from cosa.agents.decision_proxy.cosa_interface import SENDER_ID


def test_sender_id_exact_value():
    """
    Ensures:
        - SENDER_ID is the canonical decision-proxy sender address
    """
    assert SENDER_ID == "decision.proxy@lupin.deepily.ai"


def test_sender_id_is_well_formed_address():
    """
    Ensures:
        - SENDER_ID is a non-empty string shaped like an agent address
    """
    assert isinstance( SENDER_ID, str )
    assert SENDER_ID.endswith( "@lupin.deepily.ai" )
