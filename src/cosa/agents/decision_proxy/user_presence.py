#!/usr/bin/env python3
"""
User presence for the Decision Proxy: what a broken connectivity feed means.

The responder asks a feed whether the human is connected. When the feed itself
fails, one constant decides the answer, so a ruling on that question changes
one line.

Dependency Rule:
    This module never imports from notification_proxy or swe_team.
"""

import logging
import time

import requests

from cosa.agents.decision_proxy.config import (
    DEFAULT_ACTIVE_HOURS_START,
    DEFAULT_ACTIVE_HOURS_END,
    DEFAULT_TIMEZONE,
)

logger = logging.getLogger( __name__ )

SESSIONS_ENDPOINT        = "/api/websocket-sessions"
SESSIONS_TIMEOUT_SECONDS = 5

# What a feed that cannot answer is taken to mean. Rick ruled False
# ("Proxy answers"): the proxy acts as before. True would make it defer on doubt.
FEED_FAILURE_MEANS_CONNECTED = False


def user_connected_or_default( feed_fn ):
    """Ensures: returns the feed's answer as a bool, or the failure value when the feed raises."""
    try:
        return bool( feed_fn() )
    except Exception as e:
        logger.warning( f"[UserPresence] connectivity feed failed, treating the user as {'connected' if FEED_FAILURE_MEANS_CONNECTED else 'not connected'}: {e}" )
        return FEED_FAILURE_MEANS_CONNECTED


def fetch_sessions( url, headers ):
    """Ensures: returns the sessions payload from a timed GET; raises on any error."""
    response = requests.get( url, headers=headers, timeout=SESSIONS_TIMEOUT_SECONDS )
    response.raise_for_status()
    return response.json()


def sessions_feed( host, port, authorization_fn, human_user_id, own_session_id,
                   ttl_seconds=10.0, fetch_fn=None, clock=None ):
    """
    Build a feed that says whether the human has a live session other than the proxy's own.

    Requires:
        - authorization_fn returns the Authorization header value or None, read at each fetch
        - fetch_fn( url, headers ) returns the sessions payload and raises on failure

    Ensures:
        - returns a callable returning True or False
        - an empty human_user_id is never connected and makes no request
        - an answer is reused for ttl_seconds; a failed fetch raises and is not cached
    """
    fetch   = fetch_fn if fetch_fn is not None else fetch_sessions
    clock   = clock if clock is not None else time.monotonic
    url     = f"http://{host}:{port}{SESSIONS_ENDPOINT}"
    cache   = {}

    def feed():
        if not human_user_id: return False
        now = clock()
        if "at" in cache and now - cache[ "at" ] < ttl_seconds: return cache[ "answer" ]
        authorization = authorization_fn()
        headers       = { "Authorization": authorization } if authorization is not None else {}
        sessions      = fetch( url, headers )[ "sessions" ]
        answer        = any( s.get( "user_id" ) == human_user_id and s.get( "session_id" ) != own_session_id for s in sessions )
        cache.update( at=now, answer=answer )
        return answer

    return feed


def responder_presence_kwargs( config_mgr, host, port, authorization_fn, own_session_id, fetch_fn=None ):
    """Ensures: returns the responder arguments for the hours, timezone and feed from the INI."""
    return {
        "active_hours_start" : config_mgr.get( "decision proxy active hours start", default=DEFAULT_ACTIVE_HOURS_START, return_type="int" ),
        "active_hours_end"   : config_mgr.get( "decision proxy active hours end",   default=DEFAULT_ACTIVE_HOURS_END,   return_type="int" ),
        "timezone"           : config_mgr.get( "decision proxy timezone",           default=DEFAULT_TIMEZONE ),
        "user_connected_fn"  : sessions_feed(
            host, port, authorization_fn,
            config_mgr.get( "decision proxy human user id", default="" ),
            own_session_id, fetch_fn=fetch_fn
        ),
    }
