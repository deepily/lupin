#!/usr/bin/env python3
"""
User presence for the Decision Proxy: what a broken connectivity feed means.

The responder asks a feed whether the human is connected. When the feed itself
fails, one constant decides the answer, so a ruling on that question changes
one line.

Dependency Rule:
    This module never imports from notification_proxy or swe_team.
"""

# What a feed that cannot answer is taken to mean. False keeps today's behaviour
# (the proxy answers); True would make the proxy defer to the user on doubt.
FEED_FAILURE_MEANS_CONNECTED = False


def user_connected_or_default( feed_fn ):
    """Ensures: returns the feed's answer as a bool, or the failure value when the feed raises."""
    try:
        return bool( feed_fn() )
    except Exception:
        return FEED_FAILURE_MEANS_CONNECTED
