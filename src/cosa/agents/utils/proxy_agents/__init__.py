"""
Shared Proxy Agent Infrastructure — Layer 1.

Base classes and utilities shared across all proxy agents (notification proxy,
decision proxy, future domain proxies). Provides WebSocket listener, responder,
strategy protocol, configuration, and CLI argument helpers.

Modules:
    base_strategy: Protocol definition for proxy response strategies
    base_listener: WebSocket connection, auth, reconnection with exponential backoff
    base_responder: Strategy chain execution and REST response submission
    rest_submitter: Standalone REST response submission function
    base_config: Connection defaults, reconnection params, credential resolution
    base_cli: Shared CLI argument parser helpers

Dependency Rule:
    This package NEVER imports from notification_proxy, decision_proxy, or swe_team.
"""

from cosa.agents.utils.proxy_agents.base_strategy import BaseStrategy
from cosa.agents.utils.proxy_agents.base_listener import BaseWebSocketListener
from cosa.agents.utils.proxy_agents.base_responder import BaseResponder
from cosa.agents.utils.proxy_agents.rest_submitter import submit_notification_response
from cosa.agents.utils.proxy_agents.base_config import (
    DEFAULT_SERVER_HOST,
    DEFAULT_SERVER_PORT,
    RECONNECT_INITIAL_DELAY,
    RECONNECT_MAX_DELAY,
    RECONNECT_MAX_ATTEMPTS,
    RECONNECT_BACKOFF_FACTOR,
    get_credentials,
    get_anthropic_api_key,
)
from cosa.agents.utils.proxy_agents.base_cli import add_common_args

__all__ = [
    "BaseStrategy",
    "BaseWebSocketListener",
    "BaseResponder",
    "submit_notification_response",
    "DEFAULT_SERVER_HOST",
    "DEFAULT_SERVER_PORT",
    "RECONNECT_INITIAL_DELAY",
    "RECONNECT_MAX_DELAY",
    "RECONNECT_MAX_ATTEMPTS",
    "RECONNECT_BACKOFF_FACTOR",
    "get_credentials",
    "get_anthropic_api_key",
    "add_common_args",
]
