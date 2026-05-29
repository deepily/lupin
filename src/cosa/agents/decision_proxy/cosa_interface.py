#!/usr/bin/env python3
"""
COSA interface for the Decision Proxy Agent.

Defines the sender ID used for all decision proxy notifications
and REST submissions.

Dependency Rule:
    This module NEVER imports from notification_proxy or swe_team.
"""

SENDER_ID = "decision.proxy@lupin.deepily.ai"
